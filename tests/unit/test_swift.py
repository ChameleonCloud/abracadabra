from openstack.tests import base
from utils import swift
import responses
import hashlib
import uuid


BUCKET_URL = "https://chi.tacc.chameleoncloud.org:7480/swift/v1/AUTH_570aad8999f7499db99eae22fe9b29bb/chameleon-images"

swift_image_uuid = uuid.uuid4()
swift_image_uuid_string = str(swift_image_uuid)
swift_image_suffix = [str(s).zfill(6) for s in range(1, 7)]
swift_image_part_names = [f"{swift_image_uuid_string}-{s}" for s in swift_image_suffix]
swift_part_bytes = 204800000
swift_last_modified = "2022-04-15T20:13:12.953Z"


def _swift_item_json(name, item_bytes, last_modified):
    enc_name = name.encode()
    hash_name = hashlib.md5(enc_name).hexdigest()

    return {
        "name": name,
        "hash": hash_name,
        "bytes": item_bytes,
        "last_modified": last_modified,
    }


list_response_json = []
list_response_json.append(
    _swift_item_json(swift_image_uuid_string, 0, swift_last_modified)
)


for name in swift_image_part_names:
    list_response_json.append(
        _swift_item_json(name, swift_part_bytes, swift_last_modified)
    )


class TestSwift(base.TestCase):
    def setUp(self):
        self.TIMEOUT_SCALING_FACTOR = 10000
        return super().setUp()

    @responses.activate
    def test_list_swift_images(self):
        """
        We should observe one GET call to get the list of items in the bucket
        And a HEAD call for each image UUID in the above returned list

        """
        list_rsp_fake = responses.Response(
            method="GET",
            url=BUCKET_URL,
            status=200,
            json=list_response_json,
        )
        responses.add(list_rsp_fake)

        image_head_fake = responses.head(url=f"{BUCKET_URL}/{swift_image_uuid_string}")

        swift_mgr = swift.swift_manager()
        # uses yield, we must use the result to ensure it's called at least once
        item_gen = swift_mgr.list_images()
        images = list(item_gen)

        assert list_rsp_fake.call_count == 1
        assert image_head_fake.call_count == 1
