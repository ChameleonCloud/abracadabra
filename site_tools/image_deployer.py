import argparse
import datetime
import logging
import requests
import tempfile
import yaml

import openstack

from itertools import islice


logging.basicConfig(level=logging.INFO)


class Image:
    def __init__(self, name, type, base_container, scope, current_path):
        self.name = name
        self.manifest_name = name + ".manifest"
        # sites only support 1 type so we will use the one the user selected: raw or qcow2
        self.type = type
        self.disk_name = name + "." + type
        self.scope = scope
        self.base_container = base_container
        self.current_path = current_path
        self.container_path = self.base_container + "/" + self.current_path

    def __str__(self):
        return f"Image(name={self.name})"


def get_openstack_connection(cloud_name):
    return openstack.connect(cloud=cloud_name)


def get_current_value(storage_url, base_container, scope):
    url = f"{storage_url}/{base_container}/{scope}/current"
    response = requests.get(url)
    if response.status_code != 200:
        raise Exception(f"Error getting current value: {response.content}")
    logging.debug(f"Current value: {response.text.strip()}")
    return response.text.strip()


def get_available_images(
        storage_url,
        base_container,
        scope,
        current,
        image_type):
    available_images = []

    current_path = f"{scope}/{current}"
    url = f"{storage_url}/{base_container}?prefix={current_path}"
    logging.info(f"Checking available images at {url}...")
    response = requests.get(url)
    if response.status_code != 200:
        raise Exception(f"Error getting available images: {response.content}")

    current_objects = response.text.splitlines()
    logging.debug(f"Current objects: {current_objects}")
    for object in islice(current_objects, 1, None):
        object_name = object.split("/")[-1]
        if object_name.endswith(".manifest"):
            name = object_name.rstrip(".manifest")
            available_images.append(
                Image(name, image_type, base_container, scope, current_path)
            )

    return available_images


def get_site_images(connection):
    logging.info("Checking public site images...")
    images = [
        i.name
        for i in connection.image.images(
            visibility="public"
        )
    ]
    return images


def should_sync_image(image_disk_name, site_images, current):
    if image_disk_name in site_images:
        logging.info(f"Image {image_disk_name} already in site images.")
        image = image_connection.image.find_image(image_disk_name)
        image_properties = image.properties
        logging.debug(f"Image properties: {image_properties}")
        image_current_value = image_properties.get("current", None)
        logging.debug(f"Image {image_disk_name} current value: {image_current_value}")
        if image_current_value is not None and image_current_value == current:
            logging.info(f"Image {image_disk_name} is already current.")
            return False
    return True


def download_object_to_file(storage_url, path, file_name):
    url = f"{storage_url}/{path}/{file_name}"
    response = requests.get(url, stream=True)

    if response.status_code != 200:
        raise Exception(f"Error downloading object {file_name}: {response.content}")

    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        for chunk in response.iter_content(chunk_size=65536):
            temp_file.write(chunk)
            temp_file.flush()
    logging.debug(f"Downloaded object to {temp_file.name}.")
    return temp_file


def upload_image_to_glance(image_connection,
                           image_prefix,
                           image_disk_name,
                           image_file_name,
                           disk_format,
                           manifest_data):
    image_prefix_name = image_prefix + image_disk_name

    logging.info(f"Uploading image {image_disk_name} to Glance.")
    with open(image_file_name, "rb") as image_data:
        new_image = image_connection.create_image(name=image_prefix_name,
                                                  disk_format=disk_format,
                                                  container_format="bare",
                                                  visibility="private",
                                                  data=image_data,
                                                  **manifest_data)
    logging.info(f"Uploaded image {new_image.name}.")
    return new_image


def archive_image(image):
    logging.info(f"Renaming existing image {image.name}.")
    archive_date = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    build_timestamp = image.properties.get("build-timestamp")
    if build_timestamp is not None:
        build_datetime = datetime.strptime(build_timestamp, "%Y-%m-%d %H:%M:%S.%f")
        archive_date = build_datetime.strftime("%Y%m%d_%H%M%S")

    image_connection.image.update_image(
        image.id,
        name=f"{image.name}_{archive_date}"
    )

    logging.info(f"Renamed image {image.name} " + \
                 f"to {image.name}_{archive_date}.")


def promote_image(image_connection, image_disk_name, new_image):
    existing_images = list(
        image_connection.image.images(
            name=image_disk_name,
            visibility="public"
        )
    )
    logging.info(f"Promoting image {image_disk_name}.")
    if len(existing_images) == 0:
        image_connection.image.update_image(new_image.id,
                                            name=image_disk_name,
                                            visibility="public")
    elif len(existing_images) == 1:
        archive_image(existing_images[0])
        image_connection.image.update_image(new_image.id,
                                            name=image_disk_name,
                                            visibility="public")
    else:
        # we could make this a consistency check that is run upfront so we
        # don't bother with the rest of this process if something is in this
        # state
        error = "There should never be more than 1 public image with the " + \
                f"same name: {image_disk_name}! Manual intervention required."
        logging.error(error)

    logging.info(f"Promoted image {new_image.name}.")


def get_manifest_data(manifest_url):
    response = requests.get(manifest_url)
    if response.status_code != 200:
        raise Exception(f"Error downloading object {manifest_url}: {response.content}")
    return response.json()


def sync_image(storage_url,
               image_connection,
               image,
               current=None,
               image_prefix="_testing",
               image_type="qcow2",
               dry_run=False):
    # TODO: move dry run to more of the steps
    if dry_run:
        logging.info(f"DRY RUN: Syncing image {image.name}.")
    else:
        logging.info(f"Syncing image {image.name}.")
        logging.debug(f"Downloading image {image.name} from {image.container_path}.")
        manifest_url = f"{storage_url}/{image.container_path}/{image.manifest_name}"
        manifest_data = get_manifest_data(manifest_url)
        manifest_data["current"] = current
        logging.debug(f"Downloaded {image.name} manifest: {manifest_data}, downloading image file.")

        try:
            temp_file = download_object_to_file(
                storage_url,
                image.container_path,
                image.disk_name
            )

            glance_image = upload_image_to_glance(
                image_connection,
                image_prefix,
                image.disk_name,
                temp_file.name,
                image_type,
                manifest_data
            )

            try:
                temp_file.close()
            except Exception as delete_error:
                logging.error(f"Error deleting temporary file: {delete_error}. Manual cleanup required.")

            promote_image(image_connection, image.disk_name, glance_image)

        except Exception as e:
            logging.error(f"Error syncing image {image.disk_name}: {e}. Manual intervention required.")

        logging.info(f"Image {image.name} synced.")



def do_sync(storage_url,
            image_connection,
            available_images,
            site_images,
            current=None,
            image_prefix="testing_",
            image_type="qcow2",
            dry_run=False):
    logging.info(f"Syncing images (dry_run={dry_run})...")
    for available_image in available_images:
        if should_sync_image(available_image.disk_name, site_images, current):
            sync_image(
                storage_url,
                image_connection,
                available_image,
                current=current,
                image_prefix=image_prefix,
                image_type=image_type,
                dry_run=dry_run
            )
    logging.info("Sync completed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deploy images to the site.")

    parser.add_argument("--site-yaml", type=str, required=True,
                        help="A yaml file with site information for syncing.")
    parser.add_argument("--supports-yaml", type=str,
                        default="/etc/chameleon_image_tools/supports.yaml",
                        help="A yaml file with supported images.")
    parser.add_argument("--dry-run",
                        action="store_true",
                        help="Perform a dry run without making any changes.")
    # TODO(pdmars): add a force sync flag that overrides the current check

    args = parser.parse_args()

    if args.dry_run:
        logging.info("Dry run mode enabled. No changes will be made.")

    # TODO: add this stuff in?
    # loop over supported_distros to figure out release and variant
    #with open(args.supports_yaml, 'r') as f:
    #    supports = yaml.safe_load(f)

    with open(args.site_yaml, "r") as f:
        site = yaml.safe_load(f)

    base_container = site.get("image_container", "chameleon-images")
    scope = site.get("scope", "prod")
    image_type = site.get("image_type", "qcow2")
    image_prefix = site.get("image_prefix", "testing_")
    image_store_cloud = site.get("image_store_cloud", "uc_dev") # TODO: change default
    storage_url = site.get("object_store_url")
    if storage_url is None:
        raise Exception("The object_store_url is required in your site.yaml config!")

    logging.debug(f"Using base image container/scope: {base_container}/{scope}")
    image_connection = get_openstack_connection(image_store_cloud)

    current = get_current_value(storage_url, base_container, scope)
    logging.info(f"Current image: {current}")

    # TODO(pdmars): first pass we assume we will release all images, add filters
    # for different sites later that may not need all images
    available_images = get_available_images(storage_url,
                                            base_container,
                                            scope,
                                            current,
                                            image_type)

    logging.debug("Available Central Images: {}".format(
        [str(i) for i in available_images])
    )

    site_images = get_site_images(image_connection)
    logging.debug(f"Site Images: {site_images}")

    do_sync(
        storage_url,
        image_connection,
        available_images,
        site_images,
        current=current,
        image_prefix=image_prefix,
        image_type=image_type,
        dry_run=args.dry_run
    )
