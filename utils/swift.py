from collections.abc import Mapping, Generator
from utils import common, constants
import uuid
import requests
from oslo_log import log as logging
from utils.constants import (
    SWIFT_META_HEADER_PREFIX,
    IMAGE_INSTANCE_MAPPINGS,
    IMAGE_TYPE_MAPPINGS,
)
from utils.common import map_attribute_value

LOG = logging.getLogger(__name__)


class swift_list_item(object):
    chunk_name = None
    hash = None
    bytes = None
    last_modified = None
    uuid = None

    def __init__(self, header_dict: Mapping) -> None:
        self.chunk_name = header_dict.get("name")
        self.hash = header_dict.get("hash")
        self.bytes = header_dict.get("bytes")
        self.last_modified = header_dict.get("last_modified")
        self.uuid = uuid.UUID(hex=self.chunk_name)


class chi_image_swift(common.chi_image):
    uri = None

    def __init__(
        self,
        list_item: swift_list_item,
        header_dict: Mapping,
        source_uri=None,
        supported_images=[],
    ) -> None:
        """The necessary info is split between the directory listing,
        and the per-item head request, assemble into one mapping."""
        attributes = {}

        # make a copy so we can append and override
        attributes.update(header_dict)
        attributes["checksum_md5"] = list_item.hash
        attributes["uuid"] = list_item.uuid
        self.uri = source_uri

        # convert to consistent naming convention
        img_type_attributes = {}
        for field in IMAGE_TYPE_MAPPINGS:
            map_attribute_value(field, "swift", attributes, "chi", img_type_attributes)

        config_type = common.chi_image_type(**img_type_attributes)
        if supported_images:
            try:
                config_type = [i for i in supported_images if config_type == i][0]
            except IndexError:
                LOG.warn("could not load name from config")

        img_instance_attributes = {}
        for field in IMAGE_INSTANCE_MAPPINGS:
            map_attribute_value(
                field, "swift", attributes, "chi", img_instance_attributes
            )

        super().__init__(config_type, **img_instance_attributes)


class swift_manager(object):
    swift_endpoint_url = constants.CENTRALIZED_CONTAINER_URL
    swift_headers = {"Accept": "application/json"}
    supported_images = None

    def __init__(
        self, swift_endpoint_url=None, swift_headers=None, supported_images=None
    ) -> None:
        if swift_endpoint_url:
            self.swift_endpoint_url = swift_endpoint_url

        if swift_headers:
            self.swift_headers = swift_headers

        if supported_images:
            self.supported_images = supported_images

    def _get_image_detail(
        self, session: requests.Session, s_item: swift_list_item
    ) -> chi_image_swift:
        image_uuid = s_item.uuid
        image_url = f"{self.swift_endpoint_url}/{image_uuid}"
        response = session.head(url=image_url, headers=self.swift_headers)

        new_swift_image = chi_image_swift(
            list_item=s_item,
            header_dict=response.headers,
            source_uri=image_url,
            supported_images=self.supported_images,
        )
        return new_swift_image

    def list_images(self) -> Generator[chi_image_swift, None, None]:
        with requests.Session() as session:
            response = session.get(
                url=self.swift_endpoint_url, headers=self.swift_headers
            )
            data = response.json()
            for item in data:
                # Ensure list item is valid, and not a chunk
                try:
                    list_item = swift_list_item(item)
                except ValueError:
                    continue

                # Ensure only images with matching metadata are returned
                try:
                    swift_image_detail = self._get_image_detail(session, list_item)
                except ValueError as e:
                    LOG.debug(f"Skipping swift image: {e}")
                else:
                    yield swift_image_detail
