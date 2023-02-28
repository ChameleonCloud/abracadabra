from utils import common
import logging

from openstack.image.v2.image import Image
from glanceclient.client import Client as glanceClient
from keystoneauth1.session import Session as ksSession

LOG = logging.getLogger(__name__)


def filter_glance_images(session: ksSession, filters={}):
    client = glanceClient(version=2, session=session)
    image_client = client.images

    # query_params = {
    #     "visibility": "public",
    #     "name": "something",
    #     "owner": "something",
    #     "status": "something",
    #     "tag": "something",
    # }

    # TODO we can't filter based on these, as they are not 'tags'
    # query_params = {
    #     "build-distro": "ubuntu",
    #     "build-release": "focal",
    #     "build-variant": "base",
    # }

    images_generator = image_client.list(**filters)

    for glance_img in images_generator:
        try:
            glance_img = chi_glance_image(glance_img)
        except ValueError as e:
            LOG.debug(f"Skipping glance image: {e}")
        else:
            yield glance_img


class chi_glance_image(common.chi_image):
    """Define methods to map between glance images and canonical representation"""

    def __init__(self, image: Image) -> None:
        uuid = image.id
        size_bytes = image.size
        checksum_md5 = image.checksum
        revision = image.get("build-os-base-image-revision")
        build_timestamp = image.get("build-timestamp")

        # TODO: load base image name and suffix from config file
        image_type = common.chi_image_type(
            image.get("build-distro"),
            image.get("build-release"),
            image.get("build-variant"),
            None,
            None,
        )

        super().__init__(
            image_type,
            uuid,
            revision,
            build_timestamp,
            size_bytes,
            checksum_md5,
        )
