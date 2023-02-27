from utils import common
import logging
from openstack.image.v2.image import Image

LOG = logging.getLogger(__name__)


class chi_glance_image(common.chi_image):
    """Define methods to map between glance images and canonical representation"""

    def __init__(self, image: Image) -> None:
        uuid = image.id
        size_bytes = image.size
        checksum_md5 = image.checksum

        properties = image.properties
        revision = properties.get("build-os-base-image-revision")
        build_timestamp = properties.get("build-timestamp")

        distro_family = properties.get("build-distro")
        distro_release = properties.get("build-release")
        image_variant = properties.get("build-variant")

        # TODO: load base image name and suffix from config file
        image_type = common.chi_image_type(
            distro_family, distro_release, image_variant, None, None
        )

        super().__init__(
            image_type,
            uuid,
            revision,
            build_timestamp,
            size_bytes,
            checksum_md5,
        )
