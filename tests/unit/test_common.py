import uuid
from openstack.tests import base, fakes
from utils import common


fake_distro_family = "ubuntu"
fake_distro_release = "20.04"

fake_production_image_name_base = "CC-Ubuntu-20.04"
fake_production_image_name_gpu = "CC-Ubuntu-20.04-CUDA"
fake_production_image_name_fpga = "CC-Ubuntu-20.04-FPGA"
fake_production_image_name_arm64 = "CC-Ubuntu-20.04-ARM64"

fake_image_uuid = uuid.uuid4().hex
fake_image_size_bytes = "204800000"
fake_image_revision = "20230217"
fake_build_timestamp = "1665164598.226599"
fake_archival_image_name = "CC-Ubuntu-20.04-20230217-1665164598.226599"


class TestChiImageType(base.TestCase):
    def setUp(self):
        self.TIMEOUT_SCALING_FACTOR = 10000
        return super().setUp()

    def _get_image_variant(self, variant, suffix):
        return common.chi_image_type(
            family=fake_distro_family,
            release=fake_distro_release,
            variant=variant,
            prod_name=fake_production_image_name_base,
            suffix=suffix,
        )

    def test_production_name_base(self):
        img = self._get_image_variant(variant=None, suffix=None)
        assert img.production_name() == fake_production_image_name_base

    def test_production_name_gpu(self):
        img = self._get_image_variant(variant="gpu", suffix="CUDA")
        assert img.production_name() == fake_production_image_name_gpu

    def test_production_name_fpga(self):
        img = self._get_image_variant(variant="fpga", suffix="FPGA")
        assert img.production_name() == fake_production_image_name_fpga

    def test_production_name_arm64(self):
        img = self._get_image_variant(variant="arm65", suffix="ARM64")
        assert img.production_name() == fake_production_image_name_arm64


class TestChiImageBase(base.TestCase):
    def setUp(self):
        self.TIMEOUT_SCALING_FACTOR = 10000
        self.img_type = common.chi_image_type(
            family=fake_distro_family,
            release=fake_distro_release,
            variant=None,
            prod_name=fake_production_image_name_base,
            suffix=None,
        )
        return super().setUp()

    def test_archival_name(self):
        img_instance = common.chi_image(
            self.img_type,
            uuid=fake_image_uuid,
            revision=fake_image_revision,
            build_timestamp=fake_build_timestamp,
            size_bytes=fake_image_size_bytes,
            checksum_md5=None,
        )
        assert img_instance.archival_name() == fake_archival_image_name
