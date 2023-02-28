from collections.abc import Mapping, Generator
from utils import common
import uuid
import requests

import logging

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


class swift_image(common.chi_image):
    def __init__(
        self, list_item: swift_list_item, header_dict, supported_images=[]
    ) -> None:
        """The necessary info is split between the directory listing,
        and the per-item head request."""

        family = header_dict.get("x-object-meta-build-distro")
        release = header_dict.get("x-object-meta-build-release")
        variant = header_dict.get("x-object-meta-build-variant")
        size_bytes = header_dict.get("content-length")
        build_revision = header_dict.get("x-object-meta-build-os-base-image-revision")
        build_timestamp = header_dict.get("x-object-meta-build-timestamp")

        checksum_md5 = list_item.hash
        uuid = list_item.uuid

        config_type = common.chi_image_type(family, release, variant, None, None)
        if supported_images:
            try:
                config_type = [i for i in supported_images if config_type == i][0]
            except IndexError:
                LOG.warn("could not load name from config")

        super().__init__(
            config_type, uuid, build_revision, build_timestamp, size_bytes, checksum_md5
        )


class swift_manager(object):
    swift_endpoint_url = common.CENTRALIZED_CONTAINER_URL
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
    ) -> swift_image:
        image_uuid = s_item.uuid
        image_url = f"{self.swift_endpoint_url}/{image_uuid}"
        response = session.head(url=image_url, headers=self.swift_headers)

        new_swift_image = swift_image(
            s_item, response.headers, supported_images=self.supported_images
        )
        return new_swift_image

    def list_images(self) -> Generator[swift_image, None, None]:
        with requests.Session() as s:
            response = s.get(url=self.swift_endpoint_url, headers=self.swift_headers)
            data = response.json()
            for item in data:
                # Ensure list item is valid, and not a chunk
                try:
                    list_item = swift_list_item(item)
                except ValueError:
                    continue

                # Ensure only images with matching metadata are returned
                try:
                    swift_image_detail = self._get_image_detail(s, list_item)
                except ValueError as e:
                    LOG.debug(f"Skipping swift image: {e}")
                else:
                    yield swift_image_detail