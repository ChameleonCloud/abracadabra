import logging

LOG = logging.getLogger(__name__)

OBJECT_STORE_URL = "https://chi.tacc.chameleoncloud.org:7480/swift/v1"
CENRTALIZED_CONTAINER_ACCOUNT = "AUTH_570aad8999f7499db99eae22fe9b29bb"
CENTRALIZED_CONTAINER_NAME = "chameleon-images"
CENTRALIZED_CONTAINER_URL = (
    f"{OBJECT_STORE_URL}/{CENRTALIZED_CONTAINER_ACCOUNT}/{CENTRALIZED_CONTAINER_NAME}"
)


class chi_image_type(object):
    distro_family = None
    distro_release = None
    image_variant = None

    def __init__(self, family, release, variant) -> None:
        self.distro_family = family
        self.distro_release = release
        self.image_variant = variant

    def __eq__(self, other: object) -> bool:
        """Compare 3 class variables to check equality"""
        return (self.distro_family, self.distro_release, self.image_variant) == (
            getattr(other, "distro_family", None),
            getattr(other, "distro_release", None),
            getattr(other, "image_variant", None),
        )


class chi_image(chi_image_type):
    uuid = None
    name = None
    build_date = None
    size_bytes = None
    checksum_md5 = None

    def gen_canonical_name(self, family, release, variant=None, build_date=None) -> str:
        valid_tags = [t for t in [family, release, variant, build_date] if t]
        image_name = "-".join(valid_tags)
        if image_name:
            return image_name
        else:
            raise ValueError("Could not generate canonical name")

    def __init__(
        self, family, release, variant, uuid, name, build_date, size_bytes, checksum_md5
    ) -> None:
        self.uuid = uuid
        self.build_date = build_date
        self.size_bytes = size_bytes
        self.checksum_md5 = checksum_md5

        self.name = name

        super().__init__(family, release, variant)


class ChameleonImage(object):
    build_distro = None
    build_os_base_image_revision = None
    build_release = None
    build_repo = None
    build_tag = None


def archival_name(prod_image_name, image):
    return "{}-{}-{}".format(
        prod_image_name,
        image["build-os-base-image-revision"],
        image["build-timestamp"],
    )


def list_supportedimages(conn):
    """
    Fetch a list of all supported images from glance.
    To be "supported", they must satisfy:
    - owned by openstack project
    - public
    - name matches schema from image_builder
    - attached metadata == ???
    """
    images = conn.list_images()
    return images


def remove_prefix(str, prefix):
    if str.startswith(prefix):
        return str[len(prefix) :]
    else:
        return str
