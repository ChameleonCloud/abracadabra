#!/usr/bin/env python
'''
Clean up older versions of the images in Glance.
'''
import argparse
import chi
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
import json
import logging
import shlex
import subprocess
import sys
import tempfile
import ulid
from urllib.parse import urlparse
import yaml

from utils import helpers

logging.basicConfig(level=logging.INFO)


def production_name(supports, distro, release, variant):

    prod_name = supports["supported_distros"][distro]["releases"][release]["prod_name"]
    suffix = supports["supported_variants"][variant]["prod_name_suffix"]

    if suffix:
        prod_name = f"{prod_name}-{suffix}"

    return prod_name


def get_in_use_image_ids(novaclient):
    active_servers = novaclient.servers.list(
        search_opts={"status": "ACTIVE", "all_tenants": "yes"},
    )
    return set([s.image["id"] for s in active_servers])


def find_images(glanceclient, novaclient, distro, release, variant, prod_name):
    query = {
        "build-distro": distro,
        "build-release": release,
        "build-variant": variant,
        "visibility": "public",
    }

    images_in_use = get_in_use_image_ids(novaclient)

    matching_images = []
    for img in glanceclient.images.list(filters=query):
        # exclude the latest version with prod name
        if img["name"] == prod_name:
            continue
        # exclude ones that in use at the moment
        if img["id"] in images_in_use:
            logging.info(
                f"Some active instances are using Image {img['name']} (id: {img['id']})."
            )
            continue
        matching_images.append(img)

    return matching_images


def main(argv=None):
    if argv is None:
        argv = sys.argv

    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("--site-yaml", type=str, required=True,
                        help="A yaml file with site credentials.")
    parser.add_argument("--dry-run", action='store_true',
                        help="Dry run; no actual hiding and deleting")

    args = parser.parse_args(argv[1:])

    with open("/etc/chameleon_image_tools/supports.yaml", 'r') as f:
        supports = yaml.safe_load(f)

    with open(args.site_yaml, 'r') as f:
        site_specs = yaml.safe_load(f)
    hide_image_age_in_month = site_specs["hide_image_age_in_month"]
    delete_image_age_in_month = site_specs["delete_image_age_in_month"]
    if hide_image_age_in_month >= delete_image_age_in_month:
        raise ValueError(
            "Parameter hide_image_age_in_month must be smaller than delete_image_age_in_month"
        )

    today = date.today()
    hide_datetime_cutoff = today + relativedelta(months=-hide_image_age_in_month)
    delete_datetime_cuttoff = today + relativedelta(months=-delete_image_age_in_month)

    auth_session = helpers.get_auth_session_from_yaml(args.site_yaml)
    glance = chi.glance(session=auth_session)
    nova = chi.nova(session=auth_session)

    ready_to_delete_images = []
    for distro, dv in supports["supported_distros"].items():
        if "releases" not in dv:
            continue
        releases = dv["releases"]
        for release, rv in releases.items():
            if "variants" not in rv:
                continue
            for variant in rv["variants"]:
                prod_name = production_name(supports, distro, release, variant)
                ready_to_delete_images.extend(find_images(
                    glance, nova, distro, release, variant, prod_name
                ))

    skip_images = []
    if args.dry_run:
        logging.info("It's dry-run. Print messages only.")
    if "skip_images" in site_specs:
        skip_images = site_specs["skip_images"]
    for img in ready_to_delete_images:
        if img["id"] in skip_images:
            logging.info(f"Skip image {img['name']} (id: {img['id']}).")
            continue
        create_date = datetime.strptime(img["created_at"], "%Y-%m-%dT%H:%M:%SZ").date()
        if create_date <= delete_datetime_cuttoff:
            try:
                if not args.dry_run:
                    glance.images.delete(img['id'])
                logging.info(f"Image {img['name']} (id: {img['id']}) has been deleted.")
            except Exception:
                logging.exception(f"Failed to delete {img['name']} (id: {img['id']}).")
        elif create_date <= hide_datetime_cutoff:
            try:
                if not args.dry_run:
                    glance.images.update(
                        img['id'], visibility='private',
                    )
                logging.info(f"Image {img['name']} (id: {img['id']}) has been hided.")
            except Exception:
                logging.exception(f"Failed to hide {img['name']} (id: {img['id']}).")


if __name__ == '__main__':
    sys.exit(main(sys.argv))
