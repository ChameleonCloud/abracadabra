from collections import namedtuple

OBJECT_STORE_URL = "https://chi.tacc.chameleoncloud.org:7480/swift/v1"
CENRTALIZED_CONTAINER_ACCOUNT = "AUTH_570aad8999f7499db99eae22fe9b29bb"
CENTRALIZED_CONTAINER_NAME = "chameleon-images"
CENTRALIZED_CONTAINER_URL = (
    f"{OBJECT_STORE_URL}/{CENRTALIZED_CONTAINER_ACCOUNT}/{CENTRALIZED_CONTAINER_NAME}"
)
SWIFT_META_HEADER_PREFIX = "x-object-meta-"

ImageField = namedtuple("ImageField", ("chi", "glance", "swift"))

# used with getattr
IMAGE_TYPE_MAPPINGS = {
    ImageField("distro_family", "build-distro", "x-object-meta-build-distro"),
    ImageField("distro_release", "build-release", "x-object-meta-build-release"),
    ImageField("image_variant", "build-variant", "x-object-meta-build-variant"),
}

IMAGE_INSTANCE_MAPPINGS = {
    ImageField(
        "base_image_revision",
        "build-os-base-image-revision",
        "x-object-meta-build-os-base-image-revision",
    ),
    ImageField("build_timestamp", "build-timestamp", "x-object-meta-build-timestamp"),
    ImageField("build_tag", "build-tag", "x-object-meta-build-tag"),
    ImageField("build_repo", "build-repo", "x-object-meta-build-repo"),
    ImageField(
        "build_repo_commit", "build-repo-commit", "x-object-meta-build-repo-commit"
    ),
    ImageField("uuid", "id", None),
    ImageField("size_bytes", "size", None),
    ImageField("checksum_md5", "checksum", None),
}


def map_attribute_value(field: ImageField, s_type, s_obj, d_type, d_obj):
    # programatically fetch key names from a namedtuple
    # and map value between source and dest dictionary
    source_attr_key = getattr(field, s_type)
    dest_attr_key = getattr(field, d_type)

    source_attr_value = getattr(s_obj, source_attr_key, None)
    d_obj[dest_attr_key] = source_attr_value
