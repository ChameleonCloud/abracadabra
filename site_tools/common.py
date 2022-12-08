import logging
import operator
import re

import requests
from glanceclient.v2 import Client as glanceClient

from utils import helpers


class ImageSpecID(object):
    """Supported images are defined without unique identifiers"""

    distro_name = None
    distro_release = None
    image_variant = None
    ipa = "na"
    productionName = None

    def __init__(self, distro_name, distro_release, image_variant, ipa="na") -> None:
        self.distro_name = distro_name
        self.distro_release = distro_release
        self.image_variant = image_variant
        self.ipa = ipa

    def __eq__(self, other):
        """Imagespecs are equal if the name, release, variant, and ipa match.

        We're ignoring timestamps and uuid here, as they don't matter for the "spec"
        """
        assert isinstance(other, ImageSpecID)
        return (
            self.distro_name == other.distro_name
            and self.distro_release == other.distro_release
            and self.image_variant == other.image_variant
            and self.ipa == other.ipa
        )

    def __ne__(self, other):
        return not self == other

    def imageID(self):
        return ImageSpecID(
            self.distro_name, self.distro_release, self.image_variant, self.ipa
        )

    def get_identifier(self):
        return (self.distro_name, self.distro_release, self.image_variant, self.ipa)

    def glanceQuery(self):
        """Return dict to search glance API for an image matching this spec."""
        query_dict = {
            "build-distro": self.distro_name,
            "build-release": self.distro_release,
            "build-release": self.distro_release,
            "build-variant": self.image_variant,
            "build-ipa": self.ipa,
        }
        return query_dict

    def lookupProductionName(self, supports):
        """Update and return production name for image"""
        self.productionName = lookupProductionName(self.imageID(), supports=supports)
        return self.productionName


class SwiftImageID(ImageSpecID):
    timestamp = None
    uuid = None

    def __init__(
        self,
        distro_name,
        distro_release,
        image_variant,
        ipa="na",
        timestamp=None,
        uuid=None,
    ) -> None:
        super().__init__(distro_name, distro_release, image_variant, ipa)
        self.timestamp = timestamp
        self.uuid = uuid


def get_supported_image_list(supports: dict):
    """Get list of identifiers for supported images.

    Reads a dict generated from supports.yaml.
    Returns list of namedtuples.
    """

    supported_images = []

    supported_distros = [
        (distro, distro_variants.get("releases"))
        for (distro, distro_variants) in supports["supported_distros"].items()
        if distro_variants.get("releases")
    ]

    for distro_name, d_releases in supported_distros:
        for distro_release, release_variant in d_releases.items():
            for variant in release_variant.get("variants", []):

                # Handle images packageed as kernel,initramfs
                if distro_name.startswith("ipa_"):
                    kernel_id = ImageSpecID(
                        distro_name, distro_release, variant, "kernel"
                    )
                    supported_images.append(kernel_id)

                    initramfs_id = ImageSpecID(
                        distro_name, distro_release, variant, "initramfs"
                    )
                    supported_images.append(initramfs_id)
                else:
                    image_id = ImageSpecID(distro_name, distro_release, variant)
                    supported_images.append(image_id)

    return supported_images


def list_image_uuids():
    result = []
    r = requests.get(f"{helpers.CENTRALIZED_CONTAINER_URL}/")
    for item in r.content.decode().split("\n"):
        if re.match(
            "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", item
        ):
            result.append(item)
    return result


def fetch_image_content(image_id):
    r = requests.get(f"{helpers.CENTRALIZED_CONTAINER_URL}/{image_id}")
    return r.headers, r.content


def fetch_image_headers(image_id):
    r = requests.head(f"{helpers.CENTRALIZED_CONTAINER_URL}/{image_id}")
    return r.headers


def _get_swift_meta(headers, field, default=None):
    key = f"{helpers.SWIFT_META_HEADER_PREFIX}{field}"
    return headers.get(key, default)


def get_swift_image_identifier(headers):
    distro = _get_swift_meta(headers, "build-distro")
    release = _get_swift_meta(headers, "build-release")
    variant = _get_swift_meta(headers, "build-variant")
    ipa = _get_swift_meta(headers, "build-ipa")
    timestamp = _get_swift_meta(headers, "build-timestamp")
    return SwiftImageID(distro, release, variant, ipa, timestamp)


def get_available_images():
    """Get list of images available for download.

    Takes no arguments, as the image store URL is configured statically.
    Returns an interator of SwiftImageID, containing:
    - distro_name
    - distro_release
    - image_variant
    - ipa
    - timestamp
    - uuid (of swift object)
    """

    swift_ids = []
    # get all image metadatafrom the centralized object store
    image_uuids = list_image_uuids()
    # get metadata for each uuid
    for uuid in image_uuids:
        headers = fetch_image_headers(uuid)
        swift_id = get_swift_image_identifier(headers=headers)
        swift_id.uuid = uuid
        swift_ids.append(swift_id)

    return swift_ids


def get_latest_image_identifiers(image_list):
    # mapping of "generic" image identifier to specific, latest identifier
    image_id_map = {}

    for i in image_list:
        identifier = i.get_identifier()
        current_latest_image = image_id_map.get(identifier, None)
        if not current_latest_image:
            # No image found, we're latest by definition
            image_id_map[identifier] = i
        elif i.timestamp > current_latest_image.timestamp:
            # we're newer than current image
            image_id_map[identifier] = i
        else:
            # explicit continue case
            continue

    # Return list of latest swift objects
    return list(image_id_map.values())


def find_matching_published_images(
    glance_client: glanceClient, swift_image: ImageSpecID, image_production_name
):
    """Lookup glance images with matching name and metadata."""
    glance_query = swift_image.glanceQuery()
    glance_query["name"] = image_production_name
    glance_query["status"] = "active"

    # sort in order of most recent created
    glance_query["sort"] = "created_at:desc"

    matching_images = list(glance_client.images.list(filters=glance_query))
    return matching_images


def find_latest_published_image(glanceclient, headers, image_production_name):
    distro, release, variant, ipa = get_identifiers(headers)
    query = {
        "build-distro": distro,
        "build-release": release,
        "status": "active",
        "build-variant": variant,
        "name": image_production_name,
        "build-ipa": ipa,
    }

    matching_images = list(glanceclient.images.list(filters=query))
    matching_images.sort(reverse=True, key=operator.itemgetter("created_at"))
    return next(iter(matching_images), None)


def lookupProductionName(image_spec: ImageSpecID, supports):
    """Look up configured name for a supported image spec"""

    distro = image_spec.distro_name
    release = image_spec.distro_release
    variant = image_spec.image_variant
    ipa = image_spec.ipa

    try:
        prod_name = supports["supported_distros"][distro]["releases"][release][
            "prod_name"
        ]
        suffix = supports["supported_variants"][variant]["prod_name_suffix"]
    except KeyError as ex:
        logging.warning(f"Image missing from supported config: {image_spec.__dict__}")
    else:
        if suffix:
            prod_name = f"{prod_name}-{suffix}"
        if ipa != "na":
            prod_name = f"{prod_name}.{ipa}"
        return prod_name


# def get_image_metadata_by_id(image_id):
#     try:
#         return fetch_image_headers(image_id)
#     except Exception:
#         logging.exception(f"Failed to download image {image_id}.")
#         return None, None


# def get_image_obj_by_id(image_id):
#     try:
#         return fetch_image_content(image_id)
#     except Exception:
#         logging.exception(f"Failed to download image {image_id}.")
#         return None, None


# def find_latest_published_image(glanceclient, headers, image_production_name):
#     distro, release, variant, ipa = get_identifiers(headers)
#     query = {
#         "build-distro": distro,
#         "build-release": release,
#         "status": "active",
#         "build-variant": variant,
#         "name": image_production_name,
#         "build-ipa": ipa,
#     }

#     matching_images = list(glanceclient.images.list(filters=query))
#     matching_images.sort(reverse=True, key=operator.itemgetter("created_at"))
#     return next(iter(matching_images), None)


# def copy_image(session, headers, source_image_content):
#     glance = chi.glance(session=session)
#     extra = {
#         k.lower().replace(f"{helpers.SWIFT_META_HEADER_PREFIX}", ""): v
#         for k, v in headers.items()
#         if k.lower().startswith(f"{helpers.SWIFT_META_HEADER_PREFIX}build")
#     }

#     tmp_image_name = f"img-cc-prod-{ulid.ulid()}"
#     new_image = glance.images.create(
#         name=tmp_image_name,
#         visibility="private",
#         disk_format=headers[f"{helpers.SWIFT_META_HEADER_PREFIX}disk-format"],
#         container_format="bare",
#         **extra,
#     )

#     try:
#         glance.images.upload(
#             new_image["id"],
#             io.BytesIO(source_image_content),
#         )
#     except Exception as e:
#         # will raise exception if deleting fails; in this case, please
#         # manually delete the empty image!
#         glance.images.delete(new_image["id"])
#         raise e

#     return new_image


# def archive_image(auth_session, image, image_production_name):
#     glance = chi.glance(session=auth_session)

#     new_name = helpers.archival_name(image_production_name, image=image)

#     logging.info(f"renaming image {image['name']} ({image['id']}) to {new_name}")
#     glance.images.update(image["id"], name=new_name)


# def get_latest_image_objs(identifiers):
#     image_objs = {}
#     for image in list_images():
#         headers = fetch_image_headers(image)
#         image_variant = headers.get(
#             f"{helpers.SWIFT_META_HEADER_PREFIX}build-variant", None
#         )
#         image_release = headers.get(
#             f"{helpers.SWIFT_META_HEADER_PREFIX}build-release", None
#         )
#         image_distro = headers.get(
#             f"{helpers.SWIFT_META_HEADER_PREFIX}build-distro", None
#         )
#         image_ipa = headers.get(f"{helpers.SWIFT_META_HEADER_PREFIX}build-ipa", None)
#         timestamp = headers.get(
#             f"{helpers.SWIFT_META_HEADER_PREFIX}build-timestamp", None
#         )
#         identifier = (image_distro, image_release, image_variant, image_ipa)
#         if identifier in identifiers and timestamp:
#             if identifier not in image_objs:
#                 image_objs[identifier] = {"timestamp": "0"}
#             if image_objs[identifier]["timestamp"] < timestamp:
#                 image_objs[identifier] = {"timestamp": timestamp, "obj": image}

#     result = []
#     for identifier in image_objs.keys():
#         logging.info(f"Downloading image for {identifier}")
#         resp_headers, content = fetch_image_content(image_objs[identifier]["obj"])
#         yield (resp_headers, content)
