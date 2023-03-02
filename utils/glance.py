from utils import common
import logging

from openstack.image.v2.image import Image
from glanceclient.client import Client as glanceClient
from keystoneauth1.session import Session as ksSession
from glanceclient.v2.client import Client as v2Client
import openstack
from openstack.connection import Connection
from openstack import exceptions
from glanceclient.exc import HTTPNotFound, HTTPConflict

from utils.swift import chi_image_swift
from utils.constants import (
    IMAGE_TYPE_MAPPINGS,
    IMAGE_INSTANCE_MAPPINGS,
)
from utils.common import map_attribute_value

LOG = logging.getLogger(__name__)


class glance_manager(object):
    session: ksSession = None
    client: v2Client = None
    conn: Connection = None

    supported_images = []

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

    def glance_to_chi_image(self, glance_image: Image) -> common.chi_image:
        img_type_attributes = {}
        for field in IMAGE_TYPE_MAPPINGS:
            map_attribute_value(
                field, "glance", glance_image, "chi", img_type_attributes
            )

        img_instance_attributes = {}
        for field in IMAGE_INSTANCE_MAPPINGS:
            map_attribute_value(
                field, "glance", glance_image, "chi", img_instance_attributes
            )

        image_type = common.chi_image_type(**img_type_attributes)
        image_type = [i for i in self.supported_images if image_type == i][0]

        chi_image = common.chi_image(image_type, **img_instance_attributes)
        return chi_image

    def chi_to_glance_image(self, c_image: common.chi_image) -> Image:
        img_type_attributes = {}
        for field in IMAGE_TYPE_MAPPINGS:
            map_attribute_value(
                field, "chi", c_image.image_type, "glance", img_type_attributes
            )

        img_instance_attributes = {}
        for field in IMAGE_INSTANCE_MAPPINGS:
            map_attribute_value(
                field, "chi", c_image, "glance", img_instance_attributes
            )
        # glance images don't separate "type" and "per-image" attributes
        glance_image = Image(**img_type_attributes, **img_instance_attributes)
        return glance_image

    def filter_glance_images(self, filters={}):
        images_generator = self.client.images.list(**filters)

        for glance_img in images_generator:
            try:
                chi_image = self.glance_to_chi_image(glance_image=glance_img)
            except ValueError as e:
                LOG.debug(f"Skipping glance image: {e}")
            else:
                yield chi_image

    def import_image_from_swift(self, image: chi_image_swift):
        # Build the image attributes
        new_image_id = str(image.uuid)

        image_attrs = {
            "name": image.archival_name(),
            "id": new_image_id,
            "disk_format": "qcow2",
            "container_format": "bare",
            "visibility": "public",
        }

        # # create placeholder in glance DB
        try:
            glance_image: Image
            glance_image = self.client.images.create(**image_attrs)
        except HTTPConflict:
            LOG.warning(
                f"uuid {new_image_id} is already present, moving to import step"
            )
            glance_image_id = new_image_id
        else:
            glance_image_id = glance_image.id

        # # Url where glance can download the image
        uri = image.uri
        try:
            self.client.images.image_import(
                image_id=glance_image_id,
                method="web-download",
                uri=uri,
            )
        except HTTPNotFound:
            LOG.warning(
                f"image {glance_image_id} not found, still creating. Retry next run"
            )
        except HTTPConflict:
            LOG.warning(
                f"image {glance_image_id} not queued, may have been uploaded in a different thread"
            )

    def sync_image_to_glance(self, image: chi_image_swift):
        """This method takes an image with a publicly visible url in swift,
        and commands glance to download it."""

        new_image_uuid = image.uuid
        new_image_archival_name = image.archival_name()
        new_image_production_name = image.image_type.production_name()

        # Check if exact image already uploaded
        try:
            glance_image_by_uuid: Image = self.client.images.get(
                image_id=new_image_uuid
            )
        except HTTPNotFound:
            pass
        else:
            if glance_image_by_uuid and glance_image_by_uuid.status == "Active":
                LOG.warning(f"Not syncing {image}, UUID is already present")
                return
            elif glance_image_by_uuid and glance_image_by_uuid.status == "Queued":
                LOG.warning(f"Skipping image create, moving to import")

        # Check if image already uploaded and archived
        try:
            filters = {"name": new_image_archival_name, "status": "active"}
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
                ) and (image.base_image_revision == current_production_image.revision):
                    LOG.warning(f"Not syncing {image}, already uploaded as production")
                    return
            elif len(glance_image_by_production_name) > 1:
                LOG.warning(
                    f"Not syncing, Duplicates found for production image {image}"
                )
                return

        # checks passed, upload image with archival name to avoid conflicts
        LOG.warning(f"uploading archival image: {image}")
        self.import_image_from_swift(image=image)
