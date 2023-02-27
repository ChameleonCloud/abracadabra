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

# The default supports.yaml should contain configurations for these images
supported_image_names = [
    "CC-CentOS7",
    "CC-CentOS7-CUDA",
    "CC-CentOS7-FPGA",
    "CC-CentOS8-stream",
    "CC-CentOS8-stream-CUDA",
    "CC-Ubuntu18.04",
    "CC-Ubuntu18.04-CUDA",
    "CC-Ubuntu20.04",
    "CC-Ubuntu20.04-CUDA",
    "CC-Ubuntu20.04-ARM64",
    "CC-Ubuntu22.04",
    "CC-Ubuntu22.04-CUDA",
    "CC-Ubuntu22.04-ARM64",
    "CC-IPA-Debian11-AMD64",
]


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


class TestSupportsYaml(base.TestCase):
    def setUp(self):
        self.TIMEOUT_SCALING_FACTOR = 10000
        return super().setUp()

    def test_config_load(self):
        images = common.load_supported_images_from_config("supports.yaml")
        production_names = []
        for i in images:
            self.assertIsNotNone(i.distro_family)
            self.assertIsNotNone(i.distro_release)
            self.assertIsNotNone(i.image_variant)

            prod_name = i.production_name()
            production_names.append(prod_name)

            # check that each config item is a known variant
            self.assertIn(prod_name, supported_image_names)

        for sn in supported_image_names:
            # reverse check, ensure known variant is present in the config file
            self.assertIn(sn, production_names)
