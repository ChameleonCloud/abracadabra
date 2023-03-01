from utils import common
import logging

from openstack.image.v2.image import Image
from glanceclient.client import Client as glanceClient
from keystoneauth1.session import Session as ksSession
from glanceclient.v2.client import Client as v2Client
import openstack
from openstack.connection import Connection
from openstack import exceptions
from glanceclient.exc import HTTPNotFound

LOG = logging.getLogger(__name__)


class chi_glance_image(common.chi_image):
    """Define methods to map between glance images and canonical representation"""

    def __init__(self, image: Image, supported_images=[]) -> None:
        uuid = image.id
        size_bytes = image.size
        checksum_md5 = image.checksum
        revision = image.get("build-os-base-image-revision")
        build_timestamp = image.get("build-timestamp")

        # TODO: load base image name and suffix from config file
        config_type = common.chi_image_type(
            image.get("build-distro"),
            image.get("build-release"),
            image.get("build-variant"),
            None,
            None,
        )
        if supported_images:
            try:
                config_type = [i for i in supported_images if config_type == i][0]
            except IndexError:
                LOG.warn("could not load name from config")

        super().__init__(
            config_type,
            uuid,
            revision,
            build_timestamp,
            size_bytes,
            checksum_md5,
        )


class glance_manager(object):
    session: ksSession = None
    client: v2Client = None
    conn: Connection = None

    supported_images = None

    def __init__(self, session: ksSession = None, supported_images=None) -> None:
        if session:
            self.session = session
        else:
            connection = openstack.connect()
            self.session = connection.session
            self.client = glanceClient(version=2, session=self.session)
            self.conn = connection

        if supported_images:
            self.supported_images = supported_images

    def filter_glance_images(self, filters={}):
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

        images_generator = self.client.images.list(**filters)

        for glance_img in images_generator:
            try:
                glance_img = chi_glance_image(
                    glance_img, supported_images=self.supported_images
                )
            except ValueError as e:
                LOG.debug(f"Skipping glance image: {e}")
            else:
                yield glance_img

    def sync_image_to_glance(self, image: chi_glance_image):
        """This method takes an image with a publicly visible url in swift,
        and commands glance to download it."""

        new_image_uuid = image.uuid
        new_image_archival_name = image.archival_name()
        new_image_production_name = image.image_type.production_name()

        # Check if exact image already uploaded
        try:
            glance_image_by_uuid = self.client.images.get(image_id=new_image_uuid)
        except HTTPNotFound:
            pass
        else:
            if glance_image_by_uuid:
                LOG.warning(f"Not syncing {image}, UUID is already present")
                return

        # Check if image already uploaded and archived
        try:
            filters = {"name": new_image_archival_name}
            glance_image_by_archival_name = list(
                self.client.images.list(filters=filters)
            )
        except HTTPNotFound:
            pass
        else:
            if glance_image_by_archival_name:
                LOG.warning(f"Not syncing {image}, already archived on target")
                return

        # Check if exact image already uploaded and production
        try:
            filters = {"name": new_image_production_name}
            glance_image_by_production_name = list(
                self.client.images.list(filters=filters)
            )
        except HTTPNotFound:
            pass
        else:
            if len(glance_image_by_production_name) == 1:
                current_production_image = chi_glance_image(
                    glance_image_by_production_name[0]
                )
                if (
                    image.build_timestamp == current_production_image.build_timestamp
                ) and (image.revision == current_production_image.revision):
                    LOG.warning(f"Not syncing {image}, already uploaded as production")
                    return
            elif len(glance_image_by_production_name) > 1:
                LOG.warning(
                    f"Not syncing, Duplicates found for production image {image}"
                )
                return

        # checks passed, upload image with archival name to avoid conflicts
        LOG.warning(f"uploading archival image: {image}")
