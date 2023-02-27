#!/usr/bin/env python
"""
Download image from the centralized object store and deploy to the site.
"""
import argparse
import logging

from utils.common import load_supported_images_from_config
from utils import swift as chi_img_swift, glance as chi_img_glance

import openstack

LOG = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # parser.add_argument(
    #     "--site-yaml",
    #     type=str,
    #     required=True,
    #     help="A yaml file with site credentials.",
    # )
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

    args = parser.parse_args()

    # configuration for each image type, including production name and suffix
    configured_image_types = load_supported_images_from_config(args.supports_yaml)
    print(configured_image_types)

    # initiate connection to swift for reuse, as well as applying config for naming
    # swift_img_conn = chi_img_swift.swift_manager(
    #     supported_images=configured_image_types
    # )

    # available_supported_images = [
    #     i
    #     for i in swift_img_conn.list_images()
    #     if i.image_type in configured_image_types
    # ]

    # Initialize connection
    conn = openstack.connect(cloud="uc_dev_admin")

    # for each available, supported image, check if it's in glance.
    for i in conn.image.images():
        tmp_img = chi_img_glance.chi_glance_image(i)
        print(tmp_img)


if __name__ == "__main__":
    main()
