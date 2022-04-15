#!/usr/bin/env python
'''
Download image from the centralized object store and deploy to the site.
'''
import argparse
import chi
import io
import json
import logging
import operator
import re
import requests
import shlex
import subprocess
import sys
import tempfile
import ulid
from urllib.parse import urlparse
import yaml

from utils import helpers

logging.basicConfig(level=logging.INFO)


def get_identifiers(headers):
    distro = headers[f"{helpers.SWIFT_META_HEADER_PREFIX}build-distro"]
    release = headers[f"{helpers.SWIFT_META_HEADER_PREFIX}build-release"]
    variant = headers[f"{helpers.SWIFT_META_HEADER_PREFIX}build-variant"]

    return distro, release, variant


def production_name(headers, supports):
    distro, release, variant = get_identifiers(headers)

    prod_name = supports["supported_distros"][distro]["releases"][release]["prod_name"]
    suffix = supports["supported_variants"][variant]["prod_name_suffix"]

    if suffix:
        prod_name = f"{prod_name}-{suffix}"

    return prod_name


def find_latest_published_image(glanceclient, headers, image_production_name):
    distro, release, variant = get_identifiers(headers)
    query = {
        "build-distro": distro,
        "build-release": release,
        "status": "active",
        "build-variant": variant,
        "name": image_production_name,
    }

    matching_images = list(glanceclient.images.list(filters=query))
    matching_images.sort(
        reverse=True, key=operator.itemgetter('created_at'))
    return next(iter(matching_images), None)


def copy_image(session, headers, source_image_content):
    glance = chi.glance(session=session)
    extra = {
        k.lower().replace(f"{helpers.SWIFT_META_HEADER_PREFIX}", ""): v
        for k, v in headers.items()
        if k.lower().startswith(f"{helpers.SWIFT_META_HEADER_PREFIX}build")
    }

    tmp_image_name = f"img-cc-prod-{ulid.ulid()}"
    new_image = glance.images.create(
        name=tmp_image_name,
        visibility="private",
        disk_format=headers[f"{helpers.SWIFT_META_HEADER_PREFIX}disk-format"],
        container_format='bare',
        **extra
    )

    try:
        glance.images.upload(
            new_image['id'],
            io.BytesIO(source_image_content),
        )
    except Exception as e:
        # will raise exception if deleting fails; in this case, please
        # manually delete the empty image!
        glance.images.delete(new_image['id'])
        raise e

    return new_image


def archive_image(auth_session, image, image_production_name):
    glance = chi.glance(session=auth_session)

    new_name = helpers.archival_name(image_production_name, image=image)

    logging.info(
        f"renaming image {image['name']} ({image['id']}) to {new_name}"
    )
    glance.images.update(image['id'], name=new_name)


def download_image(image_id):
    r = requests.get(f"{helpers.CENTRALIZED_CONTAINER_URL}/{image_id}")
    return r.headers, r.content


def read_image_metadata(image_id):
    r = requests.head(f"{helpers.CENTRALIZED_CONTAINER_URL}/{image_id}")
    return r.headers


def list_images():
    result = []
    r = requests.get(f"{helpers.CENTRALIZED_CONTAINER_URL}/")
    for item in r.content.decode().split("\n"):
        if re.match("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", item):
            result.append(item)
    return result


def get_image_obj_by_id(image_id):
    try:
        return download_image(image_id)
    except Exception:
        logging.exception(f"Failed to download image {image_id}.")
        return None, None


def get_latest_image_objs(identifiers):
    image_objs = {}
    for image in list_images():
        headers = read_image_metadata(image)
        image_variant = headers.get(f"{helpers.SWIFT_META_HEADER_PREFIX}build-variant", None)
        image_release = headers.get(f"{helpers.SWIFT_META_HEADER_PREFIX}build-release", None)
        image_distro = headers.get(f"{helpers.SWIFT_META_HEADER_PREFIX}build-distro", None)
        timestamp = headers.get(f"{helpers.SWIFT_META_HEADER_PREFIX}build-timestamp", None)
        identifier = (image_distro, image_release, image_variant)
        if identifier in identifiers and timestamp:
            if identifier not in image_objs:
                image_objs[identifier] = {"timestamp": "0"}
            if image_objs[identifier]["timestamp"] < timestamp:
                image_objs[identifier] = {
                    "timestamp": timestamp, "obj": image
                }

    result = []
    for identifier in image_objs.keys():
        resp_headers, content = download_image(image_objs[identifier]["obj"])
        result.append((resp_headers, content))
    return result


def main(argv=None):
    if argv is None:
        argv = sys.argv

    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("--site-yaml", type=str, required=True,
                        help="A yaml file with site credentials.")
    parser.add_argument('--latest', type=str, nargs=3,
                        metavar=("distro", "release", "variant"),
                        help='Publish latest tested image given 3 args:<distro> <release> <variant>')
    parser.add_argument('--image', type=str, help='Image id to publish')

    args = parser.parse_args(argv[1:])

    with open("/etc/chameleon_image_tools/supports.yaml", 'r') as f:
        supports = yaml.safe_load(f)

    auth_session = helpers.get_auth_session_from_yaml(args.site_yaml)

    release_images = []

    if args.image:
        headers, content = get_image_obj_by_id(args.image)
        if not headers or not content:
            raise RuntimeError(f"Image {args.image} found")
        release_images.append((headers, content))
    elif args.latest:
        distro, release, variant = args.latest
        release_images = get_latest_image_objs(
            [(distro, release, variant)]
        )
    else:
        # release all images
        identifiers = []
        for distro, dv in supports["supported_distros"].items():
            if "releases" not in dv:
                continue
            releases = dv["releases"]
            for release, rv in releases.items():
                if "variants" not in rv:
                    continue
                for variant in rv["variants"]:
                    identifiers.append((distro, release, variant))
        release_images = get_latest_image_objs(identifiers)

    glance = chi.glance(session=auth_session)
    for img in release_images:
        resp_headers = img[0]
        source_image_content = img[1]
        image_production_name = production_name(resp_headers, supports)

        # check if the latest image has been published
        latest_image = find_latest_published_image(
            glance, resp_headers, image_production_name
        )
        timestamp_header = f"{helpers.SWIFT_META_HEADER_PREFIX}build-timestamp"
        revision_header = f"{helpers.SWIFT_META_HEADER_PREFIX}build-os-base-image-revision"
        if (
            latest_image and
            latest_image.get("build-timestamp", None) == resp_headers[timestamp_header] and
            latest_image.get("build-os-base-image-revision", None) == resp_headers[revision_header]
        ):
            d, r, v = get_identifiers(resp_headers)
            logging.info(
                f"The latest image {d}-{r}-{v} has been released. Nothing to do."
            )
            continue

        # publish image
        new_image = copy_image(
            auth_session, resp_headers, source_image_content
        )

        # rename old image
        with open(args.site_yaml, 'r') as f:
            site = yaml.safe_load(f)
        named_images = list(glance.images.list(filters={
            'name': image_production_name,
            'owner': site["admin_project"],
            'visibility': 'public'}
        ))
        if len(named_images) == 1:
            archive_image(auth_session, named_images[0], image_production_name)
        elif len(named_images) > 1:
            raise RuntimeError(
                'multiple images with the name "{}"'
                .format(image_production_name))
        elif len(named_images) < 1:
            # do nothing
            logging.info(f"no public production images {image_production_name} found on site")

        # rename new image
        glance.images.update(
            new_image["id"],
            name=image_production_name,
            visibility="public",
        )
        logging.info(f"{image_production_name} has been published successfully!")


if __name__ == '__main__':
    sys.exit(main(sys.argv))
