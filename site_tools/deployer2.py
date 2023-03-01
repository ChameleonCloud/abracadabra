#!/usr/bin/env python
"""
Download image from the centralized object store and deploy to the site.
"""
import argparse
import logging

from utils.common import load_supported_images_from_config
from utils import swift as cc_swift, glance as cc_glance
import openstack


LOG = logging.getLogger()


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
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
    parser.add_argument("--image", type=str, help="Image id to publish")
    parser.add_argument("--debug", action="store_true", help="Enable debug logs")

    args = parser.parse_args()

    if args.debug:
        # openstack.enable_logging(debug=True)
        LOG.setLevel("DEBUG")

    # configuration for each image type, including production name and suffix
    configured_image_types = load_supported_images_from_config(args.supports_yaml)

    # initiate connection to swift for reuse, as well as applying config for naming
    swift_img_conn = cc_swift.swift_manager(supported_images=configured_image_types)
    swift_image_generator = swift_img_conn.list_images()
    swift_image_set = set(swift_image_generator)

    # Initialize connection
    glance_img_conn = cc_glance.glance_manager(supported_images=configured_image_types)

    glance_image_generator = glance_img_conn.filter_glance_images()
    glance_image_set = set(glance_image_generator)

    # list images present in swift, but not in glance
    # TODO: not correctly removing images found in glance
    unsynced_images = swift_image_set.difference(glance_image_set)

    def _isLatest(img, img_set):
        return False

    # Select what to synchronize
    if args.image:
        """Sync single image by UUID."""
        images_to_sync = [i for i in unsynced_images if i.uuid == args.image]
    elif args.latest:
        """Sync latest image for each supported type."""
        images_to_sync = [i for i in unsynced_images if _isLatest(i, unsynced_images)]
    else:
        """Sync all versions for each supported type."""
        images_to_sync = unsynced_images

    # perform sync
    for img in images_to_sync:
        glance_img_conn.sync_image_to_glance(img)


if __name__ == "__main__":
    main()
