import argparse
import datetime
import json
import logging
import tempfile
import yaml

import openstack

from itertools import islice

from swiftclient.client import Connection as SwiftConnection


logging.basicConfig(level=logging.INFO)


class Image:
    def __init__(self, name, base_container, scope, current_path):
        self.name = name
        self.manifest_name = name + ".manifest"
        self.raw_name = name + ".raw"
        self.qcow_name = name + ".qcow2"
        self.scope = scope
        self.base_container = base_container
        self.current_path = current_path
        self.container_path = self.base_container + "/" + self.current_path

    def __str__(self):
        return f"Image(name={self.name})"


def get_openstack_connection(cloud, cloud_name):
    return openstack.connect(auth_url=cloud['clouds'][cloud_name]["auth"]["auth_url"],
                             auth_type="v3applicationcredential",
                             application_credential_id=cloud['clouds'][cloud_name]["auth"]["application_credential_id"],
                             application_credential_secret=cloud['clouds'][cloud_name]["auth"]["application_credential_secret"],
                             region_name=cloud['clouds'][cloud_name]["region_name"])


def get_current_value(connection, base_container, scope):
    _, current = connection.get_object(base_container, scope + "/current")
    return current.strip()


def get_available_images(connection, base_container, scope, current):
    logging.info("Checking available images...")
    available_images = []

    current_path = scope + "/" + current
    current_objects = connection.object_store.objects(base_container,
                                                      prefix=current_path,
                                                      delimiter="/")

    for obj in islice(current_objects, 1, None):
        object_name = obj.name.split("/")[-1]
        logging.debug(f"Checking object: {object_name}")
        if object_name.endswith(".manifest"):
            name = object_name.rstrip(".manifest")
            available_images.append(Image(name, base_container, scope, current_path))

    return available_images


def get_site_images(connection):
    logging.info("Checking site images...")
    images = [i.name for i in connection.image.images()]
    return images


def should_sync_image(image_name, site_images, current):
    if image_name in site_images:
        logging.info(f"Image {image_name} already in site images.")
        image = image_connection.image.find_image(image_name)
        image_properties = image.properties
        logging.debug(f"Image properties: {image_properties}")
        image_current_value = image_properties.get("current", None)
        logging.info(f"Image {image_name} current value: {image_current_value}")
        if image_current_value is not None and image_current_value == current:
            logging.info(f"Image {image_name} is already current.")
            return False
    return True


def setup_swift_connection(openstack_conn):
    auth_token = openstack_conn.auth_token
    storage_url = openstack_conn.object_store.get_endpoint()
    swift_conn = SwiftConnection(
        preauthtoken=auth_token,
        preauthurl=storage_url,
        auth_version='3'
    )
    return swift_conn


def download_image_to_temp_file(swift_conn, container, container_path, image_name):
    logging.debug(f"Downloading image {image_name} from {container_path}.")
    _, image_contents = swift_conn.get_object(container_path, image_name, resp_chunk_size=65536)
    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        for chunk in image_contents:
            temp_file.write(chunk)
            temp_file.flush()
    logging.debug(f"Downloaded image to {temp_file.name}.")
    return temp_file


def upload_image_to_glance(image_connection,
                           image_prefix,
                           image_name,
                           image_file_name,
                           disk_format,
                           manifest_data):
    image_prefix_name = image_prefix + image_name

    # TODO: need admin creds to make visibility public instead of private
    # right now I am using app creds that just have a member role
    logging.info(f"Uploading image {image_name} to Glance.")
    with open(image_file_name, "rb") as image_data:
        new_image = image_connection.create_image(name=image_prefix_name,
                                                disk_format=disk_format,
                                                container_format="bare",
                                                visibility="private",
                                                data=image_data,
                                                **manifest_data)
    logging.info(f"Uploaded image {new_image.name}.")
    return new_image


def archive_image(image_connection, image_name, new_image):
    # TODO: if things go sideways in here we may be in a bad state. add more error handling
    # rename the old image: this should only ever be 1. assert that instead?
    existing_images = list(image_connection.image.images(name=image_name))
    if len(existing_images) > 0:
        logging.info(f"Renaming existing image {image_name}.")
        archive_date = datetime.datetime.now().strftime("%Y%m%d_%H%M")
        for existing_image in existing_images:
            image_connection.image.update_image(existing_image.id, name=f"{image_name}_{archive_date}")
            logging.info(f"Renamed image {existing_image.name} to {existing_image.name}_{archive_date}.")
    image_connection.image.update_image(new_image.id, name=image_name)
    logging.info(f"Renamed image {new_image.id} to {image_name}.")


def sync_image(image,
               object_connection,
               image_connection,
               current,
               image_prefix="_testing",
               dry_run=False):
    logging.info(f"Syncing image {image.name}")
    # TODO: move dry run to more of the steps
    if dry_run:
        logging.info(f"DRY RUN: Syncing image {image.name}.")
    else:
        logging.info(f"Syncing image {image.name}.")

        logging.info(f"Downloading image {image.name} from {image.container_path}.")
        manifest_object = object_connection.object_store.download_object (
            container=image.container_path,
            obj=image.manifest_name
        )
        manifest_data = json.loads(manifest_object.decode('utf-8'))
        manifest_data["current"] = current
        logging.debug(f"Downloaded {image.name} manifest: {manifest_data}, downloading image file.")

        try:
            # we need to use swift directly here because the images may be too large to fit
            # in memory as they are downloaded and the swift client supports chunked downloads
            swift_conn = setup_swift_connection(object_connection)
            temp_raw_file = download_image_to_temp_file(
                swift_conn,
                image.base_container,
                image.container_path,
                image.raw_name
            )
            temp_qcow_file = download_image_to_temp_file(
                swift_conn,
                image.base_container,
                image.container_path,
                image.qcow_name
            )
            swift_conn.close()

            raw_image = upload_image_to_glance(
                image_connection,
                image_prefix,
                image.raw_name,
                temp_raw_file.name,
                "raw",
                manifest_data
            )
            qcow_image = upload_image_to_glance(
                image_connection,
                image_prefix,
                image.qcow_name,
                temp_raw_file.name,
                "qcow2",
                manifest_data
            )
        except Exception as e:
            logging.error("Error downloading images and uploading to Glance: {e}")
            # make sure we cleanup if we have a problem downloading images and uploading to Glance
            try:
                temp_raw_file.close()
                temp_qcow_file.close()
            except Exception as delete_error:
                logging.error(f"Error deleting temporary files: {delete_error}. Manual cleanup required.")

        try:
            temp_raw_file.close()
            temp_qcow_file.close()
        except Exception as delete_error:
            logging.error(f"Error deleting temporary files: {delete_error}. Manual cleanup required.")

        archive_image(image_connection, image.raw_name, raw_image)
        archive_image(image_connection, image.qcow_name, qcow_image)

        logging.info(f"Image {image.name} synced.")



def do_sync(object_connection,
            image_connection,
            current,
            available_images,
            site_images,
            image_prefix="testing_",
            dry_run=False):
    logging.info(f"Syncing images (dry_run={dry_run})...")
    for available_image in available_images:
        should_sync_raw = should_sync_image(available_image.raw_name, site_images, current)
        should_sync_qcow = should_sync_image(available_image.qcow_name, site_images, current)
        # sync both if either need syncing
        if should_sync_raw or should_sync_qcow:
            sync_image(
                available_image,
                object_connection,
                image_connection,
                current,
                image_prefix=image_prefix,
                dry_run=dry_run
            )
    logging.info("Image sync completed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deploy images to the site.")

    parser.add_argument("--cloud-yaml", type=str, required=True,
                        help="A yaml file with cloud credentials.")
    parser.add_argument("--site-yaml", type=str, required=True,
                        help="A yaml file with site information for syncing.")
    parser.add_argument("--supports-yaml", type=str,
                        default="/etc/chameleon_image_tools/supports.yaml",
                        help="A yaml file with supported images.")

    # TODO(pdmars): change these defaults for each cloud eventually
    parser.add_argument("--object-store-cloud", type=str, default="chi_uc",
                        help="The cloud to use to pull images from Swift.")
    parser.add_argument("--image-store-cloud", type=str, default="uc_dev",
                        help="The cloud to use to push images to in Glance.")
    parser.add_argument("--image-prefix", type=str, default="testing_",
                        help="The prefix to use for images in Glance.")
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

    with open(args.cloud_yaml, "r") as f:
        cloud = yaml.safe_load(f)

    with open(args.site_yaml, "r") as f:
        site = yaml.safe_load(f)

    base_container = site.get("image_container", "chameleon-images")
    scope = site.get("scope", "prod")
    logging.info(f"Using base image container/scope: {base_container}/{scope}")

    object_connection = get_openstack_connection(cloud, args.object_store_cloud)
    image_connection = get_openstack_connection(cloud, args.image_store_cloud)

    current = get_current_value(object_connection, base_container, scope)
    logging.info(f"Current image: {current}")

    # TODO(pdmars): first pass we assume we will release all images, add filters
    # for different sites later that may not need all images
    available_images = get_available_images(object_connection,
                                            base_container,
                                            scope,
                                            current)

    logging.debug("Available Central Images: {}".format(
        [str(i) for i in available_images])
    )

    site_images = get_site_images(image_connection)
    logging.debug(f"Site Images: {site_images}")

    do_sync(
        object_connection,
        image_connection,
        current,
        available_images,
        site_images,
        image_prefix=args.image_prefix,
        dry_run=args.dry_run
    )
