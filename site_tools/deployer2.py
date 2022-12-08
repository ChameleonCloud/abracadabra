#!/usr/bin/env python
"""
Download image from the centralized object store and deploy to the site.
"""
import argparse
import json
import logging
import sys

import common
import glanceclient
import yaml

from utils import helpers

logging.basicConfig(level=logging.INFO)


def main(argv=None):

    # TODO we get argv for some reason?
    if argv is None:
        argv = sys.argv

    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--site-yaml",
        type=str,
        required=True,
        help="A yaml file with site credentials.",
    )
    parser.add_argument(
        "--supports-yaml",
        type=str,
        default="/etc/chameleon_image_tools/supports.yaml",
        help="A yaml file with supported images.",
    )
    parser.add_argument(
        "--latest",
        type=str,
        nargs=3,
        metavar=("distro", "release", "variant"),
        help="Publish latest tested image given 3 args:<distro> <release> <variant>",
    )
    parser.add_argument(
        "--ipa",
        type=str,
        default="na",
        choices=["initramfs", "kernel"],
        help='IPA metadata; if not IPA image, set to "na"; default "na"',
    )
    parser.add_argument("--image", type=str, help="Image id to publish")

    args = parser.parse_args(argv[1:])

    # three operational modes:
    # 1. Get specific image by uuid
    # 2. Get "latest" image for specific variant
    # 3. Get latest version of all supported variants

    with open(args.supports_yaml, "r") as f:
        supports = yaml.safe_load(f)

    # Set of identifers for all "supported" iamges
    supported_images = common.get_supported_image_list(supports)
    # get swift image identifer for each UUID in object store
    available_images = common.get_available_images()

    missing_supported_images = [
        i.get_identifier() for i in supported_images if i not in available_images
    ]
    if missing_supported_images:
        logging.warning(
            f"The following suported images are missing from the object store: {missing_supported_images}"
        )

    # use the list of images from swift, since they have timestamps
    available_supported_images = [
        i for i in available_images if i.imageID() in supported_images
    ]
    latest_available_supported_images = common.get_latest_image_identifiers(
        available_supported_images
    )
    # for each latest image, check if the site has it already

    auth_session = helpers.get_auth_session_from_yaml(args.site_yaml)
    glance_client = glanceclient.Client(version=2, session=auth_session)

    for swift_image in latest_available_supported_images:
        image_production_name = swift_image.lookupProductionName(supports=supports)
        matching_images = common.find_matching_published_images(
            glance_client, swift_image, image_production_name
        )
        num_matches = len(matching_images)
        logging.info(f"found {num_matches} for {image_production_name} in glance")

    # for image_id, swift_image in latest_images:


if __name__ == "__main__":
    sys.exit(main(sys.argv))
