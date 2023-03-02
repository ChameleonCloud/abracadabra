import yaml

from oslo_log import log as logging
from utils import constants

LOG = logging.getLogger(__name__)


class chi_image_type(object):
    distro_family = None
    distro_release = None
    image_variant = None

    production_name_base = ""
    production_name_suffix = ""

    def __init__(
        self,
        distro_family,
        distro_release,
        image_variant,
        prod_name="",
        suffix="",
        **kwargs,
    ) -> None:
        self.distro_family = distro_family
        self.distro_release = distro_release
        self.image_variant = image_variant
        self.production_name_base = prod_name
        self.production_name_suffix = suffix

        if not distro_family or not distro_release or not image_variant:
            raise ValueError("Supplied image type missing required identifier")

    def __eq__(self, other: object) -> bool:
        """Compare 3 class variables to check equality"""
        return (self.distro_family, self.distro_release, self.image_variant) == (
            getattr(other, "distro_family", None),
            getattr(other, "distro_release", None),
            getattr(other, "image_variant", None),
        )

    def __hash__(self) -> int:
        # production name, and it's components, are configurable, and don't uniquely
        # identify a "supported image". instead, use tuple of family, release, variant
        identifier = (self.distro_family, self.distro_release, self.image_variant)
        return hash(identifier)

    def __repr__(self) -> str:
        return self.production_name()

    def production_name(self):
        if self.production_name_suffix:
            return f"{self.production_name_base}-{self.production_name_suffix}"
        else:
            return self.production_name_base


class chi_image(object):
    # common fields to all images
    uuid = None
    size_bytes = None
    checksum_md5 = None

    # per-image provenance fields
    base_image_revision = None
    build_timestamp = None
    build_repo = None
    build_repo_commit = None
    build_tag = None

    def _identifier(self):
        """Define tuple to use for hashing and comparison"""
        return (
            self.image_type.distro_family,
            self.image_type.distro_release,
            self.image_type.image_variant,
            self.base_image_revision,
            self.build_timestamp,
        )

    def __init__(
        self,
        image_type: chi_image_type,
        uuid,
        base_image_revision,
        build_timestamp,
        size_bytes,
        checksum_md5=None,
        build_repo=None,
        build_repo_commit=None,
        build_tag=None,
        **kwargs,
    ) -> None:
        self.image_type = image_type
        self.uuid = uuid
        self.base_image_revision = base_image_revision
        self.build_timestamp = build_timestamp
        self.size_bytes = size_bytes
        self.checksum_md5 = checksum_md5
        self.build_repo = build_repo
        self.build_repo_commit = build_repo_commit
        self.build_tag = build_tag

        if not uuid or not base_image_revision or not build_timestamp:
            raise ValueError("Supplied image missing required identifier")

    def archival_name(self) -> str:
        return "{}-{}-{}".format(
            self.image_type.production_name(),
            self.base_image_revision,
            self.build_timestamp,
        )

    # To use a class in Set comparisons, both __hash__ and __eq__ must be defined.
    # If __eq__ returns true for two objects, __hash__ must return the same value for both.
    def __hash__(self) -> int:
        return hash(self._identifier())

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, chi_image) and self._identifier() == other._identifier()
        )

    # Define __repr__ to make logs and debugging more human readable
    def __repr__(self) -> str:
        return self.archival_name()


def load_supported_images_from_config(config_file_path):
    config = {}
    with open(config_file_path, "r") as fp:
        config = yaml.safe_load(fp)

    supported_distros_dict = config.get("supported_distros")
    supported_variants_dict = config.get("supported_variants")

    supported_images = set()

    for distro_name, distro_values in supported_distros_dict.items():
        for release_name, release_values in distro_values.get("releases").items():
            for variant_name in release_values.get("variants", []):
                variant_details = supported_variants_dict.get(variant_name)

                try:
                    image = chi_image_type(
                        distro_family=distro_name,
                        distro_release=release_name,
                        image_variant=variant_name,
                        prod_name=release_values.get("prod_name"),
                        suffix=variant_details.get("prod_name_suffix"),
                    )
                except ValueError:
                    continue
                else:
                    supported_images.add(image)

    return supported_images


def map_attribute_value(field: constants.ImageField, s_type, s_obj, d_type, d_obj):
    def _resolve(obj, spec):
        """Attempt to get value from class or dict"""
        try:
            # if dict-like
            value = obj[spec]
        except (TypeError, KeyError):
            # if class-like
            value = getattr(obj, spec, None)
        return value

    # programatically fetch key names from a namedtuple
    # and map value between source and dest dictionary
    source_attr_key = getattr(field, s_type)
    dest_attr_key = getattr(field, d_type)
    if source_attr_key and dest_attr_key:
        source_attr_value = _resolve(s_obj, source_attr_key)
        d_obj[dest_attr_key] = source_attr_value
