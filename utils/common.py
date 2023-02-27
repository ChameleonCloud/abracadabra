import logging

LOG = logging.getLogger(__name__)

OBJECT_STORE_URL = "https://chi.tacc.chameleoncloud.org:7480/swift/v1"
CENRTALIZED_CONTAINER_ACCOUNT = "AUTH_570aad8999f7499db99eae22fe9b29bb"
CENTRALIZED_CONTAINER_NAME = "chameleon-images"
CENTRALIZED_CONTAINER_URL = (
    f"{OBJECT_STORE_URL}/{CENRTALIZED_CONTAINER_ACCOUNT}/{CENTRALIZED_CONTAINER_NAME}"
)


class chi_image_type(object):
    distro_family = None
    distro_release = None
    image_variant = None

    production_name_base = None
    production_name_suffix = None

    def __init__(self, family, release, variant, prod_name=None, suffix=None) -> None:
        self.distro_family = family
        self.distro_release = release
        self.image_variant = variant
        self.production_name_base = prod_name
        self.production_name_suffix = suffix

    def __eq__(self, other: object) -> bool:
        """Compare 3 class variables to check equality"""
        return (self.distro_family, self.distro_release, self.image_variant) == (
            getattr(other, "distro_family", None),
            getattr(other, "distro_release", None),
            getattr(other, "image_variant", None),
        )

    def production_name(self):
        if self.production_name_suffix:
            return f"{self.production_name_base}-{self.production_name_suffix}"
        else:
            return self.production_name_base


class chi_image(object):
    uuid = None
    name = None
    revision = None
    build_timestamp = None
    size_bytes = None
    checksum_md5 = None

    def __init__(
        self,
        image_type: chi_image_type,
        uuid,
        revision,
        build_timestamp,
        size_bytes,
        checksum_md5,
    ) -> None:
        self.image_type = image_type
        self.uuid = uuid
        self.revision = revision
        self.build_timestamp = build_timestamp
        self.size_bytes = size_bytes
        self.checksum_md5 = checksum_md5

    def archival_name(self) -> str:
        return "{}-{}-{}".format(
            self.image_type.production_name(),
            self.revision,
            self.build_timestamp,
        )
