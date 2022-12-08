#!/usr/bin/env python
"""
Download image from the centralized object store and deploy to the site.
"""
import argparse
import logging
import sys
from datetime import datetime

import common
import glanceclient
import yaml

from utils import helpers

# logging.basicConfig(level=logging.DEBUG)
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

    auth_session = helpers.get_auth_session_from_yaml(args.site_yaml)
    glance_client = glanceclient.Client(version=2, session=auth_session)

    # three operational modes:
    # 1. Get specific image by uuid
    # 2. Get "latest" image for specific variant
    # 3. Get latest version of all supported variants

    with open(args.supports_yaml, "r") as f:
        supports = yaml.safe_load(f)

    # Set of identifers for all "supported" iamges
    supported_images = common.get_supported_image_list(supports)

    # Check glance for images matching the supported image name
    for image in supported_images:
        production_name = image.lookupProductionName(supports)
        glance_filter = {
            "name": production_name,
            "visibility": "public",
        }
        matching_images = list(glance_client.images.list(filters=glance_filter))

        for gi in matching_images:
            try:
                archival_name = helpers.archival_name(production_name, gi)
            except KeyError as ex:
                logging.warning(f"glance image {gi.id} is missing build date")
                archival_name = f"{production_name}-{gi.created_at}"

            print(production_name, archival_name)


#     # get swift image identifer for each UUID in object store
#     available_images = common.get_available_images()

#     # we have 4 combinations to care about from available, supported
#     # we care only about supported images, and can ignore anything unsupported that happens to be available in swift

#     # warn about un-downloadable supported images. This should only happen when we've first added a new suppported image,
#     # but it hasn't been published yet.
#     missing_supported_images = [
#         i.get_identifier() for i in supported_images if i not in available_images
#     ]
#     if missing_supported_images:
#         logging.warning(
#             f"The following suported images are missing from the object store: {missing_supported_images}"
#         )

#     # For available supported images, use the list from swift instead of the config file, since they have timestamps,
#     # and we want the latest ones.
#     available_supported_images = [
#         i for i in available_images if i.imageID() in supported_images
#     ]
#     latest_available_supported_images = common.get_latest_image_identifiers(
#         available_supported_images
#     )

#     # for each latest image, check if the site has the current version of the image in glance

#     images_to_download = []

#     for swift_image in latest_available_supported_images:
#         image_production_name = swift_image.lookupProductionName(supports=supports)
#         matching_images = common.find_matching_published_images(
#             glance_client, swift_image, image_production_name
#         )

#         # if image is missing, always download it
#         if len(matching_images) == 0:
#             logging.info(
#                 f"Site missing image for {image_production_name}, downloading."
#             )
#             images_to_download.append(swift_image)
#             continue
#         elif len(matching_images) == 1:
#             # if image present, but older, download it
#             swift_timestamp = datetime.fromtimestamp(float(swift_image.timestamp))
#             for gi in matching_images:
#                 glance_timestamp = datetime.strptime(
#                     gi.created_at, "%Y-%m-%dT%H:%M:%SZ"
#                 )

#                 if swift_timestamp >= glance_timestamp:
#                     logging.info(
#                         f"Glance image {gi.id} older than swift {swift_image.uuid}, proceeding to download"
#                     )
#                     images_to_download.append(swift_image)
#                 else:
#                     logging.info(
#                         f"Glance image {gi.id} newer than swift {swift_image.uuid}, nothing to do"
#                     )
#         elif len(matching_images) > 1:
#             logging.error(
#                 f"multiple images present that match {image_production_name}, this will impact users"
#             )

#     for image in images_to_download:
#         print(f"need to download {image}")
#         """
#         Steps, for each uuid in swift:
#         1. Download image content to local tmpdir
#         2. create new image with content, and tmp name
#         3. name new image to production name
#         4. name old image to archival names
#         """


if __name__ == "__main__":
    sys.exit(main(sys.argv))