import uuid
from openstack.tests import base, fakes
from utils import common

fake_image_uuid = uuid.uuid4().hex
fake_glance_image = fakes.make_fake_image(image_id=fake_image_uuid)


class TestGlance(base.TestCase):
    def setUp(self):
        self.TIMEOUT_SCALING_FACTOR = 10000
        return super().setUp()

    def test_image_list(self):
        raise NotImplemented

    def test_upload_new_image(self):
        raise NotImplemented

    def test_archive_image(self):
        raise NotImplemented

    def test_safe_promote_image(self):
        raise NotImplemented
