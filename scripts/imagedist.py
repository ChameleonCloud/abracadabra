#!/usr/bin/env python
'''
Distribute images to the centralized object store.

JSON auth file should be of format:

    {"auths": {"<site1>": {"<OS_var>": "<value>", ...}, ...}}

The source image will be copied to the centralized object store.
And send notifications.
'''
import argparse
import chi
import json
import operator
import os
import shlex
import subprocess
import sys
import tempfile
from urllib.parse import urlparse
import yaml

sys.path.append("..")
from utils import helpers

BASE_PROPS = {
    'checksum',
    'container_format',
    'created_at',
    'disk_format',
    'file',
    'id',
    'min_disk',
    'min_ram',
    'name',
    'owner',
    'protected',
    'schema',
    'self',
    'size',
    'status',
    'tags',
    'updated_at',
    'virtual_size',
    'visibility',
}


def production_name(image=None, distro=None, release=None, variant=None):
    if image:
        distro = image["build-distro"]
        release = image["build-release"]
        variant = image["build-variant"]

    with open("../supports.yaml", 'r') as f:
        supports = yaml.safe_load(f)

    prod_name = supports["supported_distros"][distro]["releases"][release]["prod_name"]
    suffix = supports["supported_variants"][variant]["prod_name_suffix"]

    if suffix:
        prod_name = f"{prod_name}-{suffix}"

    return prod_name


def extract_extra_properties(image):
    return {k: image[k] for k in image if k not in BASE_PROPS}


def copy_image(source_session, target_session, source_image_id):
    glance = chi.glance(session=source_session)
    source_image = glance.images.get(source_image_id)
    extra = extract_extra_properties(source_image)

    with tempfile.TemporaryDirectory() as tempdir:
        img_file = os.path.join(tempdir, 'image')

        glance_source = chi.glance(session=source_session)
        data = glance_source.images.data(source_image['id'])
        with open(img_file, "wb") as f:
            for chunk in data:
                f.write(chunk)

        glance_target = chi.glance(session=target_session)
        disk_format = source_image['disk_format']
        new_image = glance_target.images.create(
            name=source_image['name'],
            visibility=source_image['visibility'],
            disk_format=disk_format,
            container_format='bare',
            **extra)

        try:
            glance_target.images.upload(
                new_image['id'],
                open(img_file, "rb"),
                backend=helpers.CENTRALIZED_STORE,
            )
        except Exception as e:
            # will raise exception if deleting fails; in this case, please
            # manually delete the empty image!
            glance_target.images.delete(new_image['id'])
            raise e

        new_image_full = glance_target.images.get(new_image['id'])
        if new_image_full['checksum'] != source_image['checksum']:
            # skip checksum check for kvm site
            raise RuntimeError('checksum mismatch')

        # add metadata to swift object
        swift_conn = helpers.connect_to_swift_with_admin(
            target_session, helpers.CENTRALIZED_STORE_REGION_NAME
        )
        try:
            meta_headers = {
                f"{helpers.SWIFT_META_HEADER_PREFIX}{k}": f"{new_image[k]}"
                for k in new_image.keys() if k.startswith("build")
            }
            meta_headers[f"{helpers.SWIFT_META_HEADER_PREFIX}disk-format"] = new_image["disk_format"]
            swift_conn.put_object(
                container=helpers.CENTRALIZED_CONTAINER_NAME,
                name=new_image['id'],
                headers=meta_headers
            )
        except Exception as e:
            glance_target.images.delete(new_image['id'])
            raise e

    return new_image_full


def archive_image(auth_session, owner, image):
    '''
    auth : Auth object
        Authentication/authorization object indicating site to target.
    image : str or dict
        ID of image to archive or dictionary with contents. New name autogenerated based on metadata.
    '''
    glance = chi.glance(session=auth_session)
    if isinstance(image, str):
        image = glance.images.get(image)

    new_name = helpers.archival_name(production_name(image=image), image=image)

    print('renaming image {} ({}) to {}'.format(
        image['name'], image['id'], new_name))
    glance.images.update(image['id'], name=new_name)


def main(argv=None):
    if argv is None:
        argv = sys.argv

    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument('auth_jsons', type=str,
                        help='File with auth info in JSON format for core sites.')
    parser.add_argument('--from-site', type=str,
                        default="tacc",
                        help='Staging image located site')
    parser.add_argument('--latest', type=str, nargs=3,
                        metavar=('distro', 'release', 'variant'),
                        help='Publish latest tested image given 3 args:<distro> <release> <variant>')
    parser.add_argument('--image', type=str, help='Image id to publish')
    parser.add_argument('--notify', type=str, nargs=2,
                        help="Send notifications to emails (comma-separated)"
                        " using relay: <relay> <emails>")

    args = parser.parse_args(argv[1:])

    with open(args.auth_jsons) as f:
        auth_data = json.load(f)

    auth_sessions = {}
    for site, auth_info in auth_data['auths'].items():
        if site in helpers.CHAMELEON_CORE_SITES:
            auth_sessions[site] = helpers.get_auth_session_from_rc(auth_info)

    centralized_auth_session = auth_sessions[helpers.CENTRALIZED_STORE_SITE]

    glance_source = chi.glance(session=auth_sessions[args.from_site])

    if args.image:
        source_image = glance_source.get(args.image)
        print('found specified image {} ({}) to publish'.format(
            source_image['name'], source_image['id']))
    elif args.latest:
        distro, release, variant = args.latest
        query = {
            'build-distro': distro,
            'build-release': release,
            'status': 'active',
            'build-variant': variant,
        }

        matching_images = list(glance_source.images.list(filters=query))
        matching_images.sort(
            reverse=True, key=operator.itemgetter('created_at'))
        latest_image = next(iter(matching_images), None)
        if not latest_image:
            print(
                f"No latest image found with query {query}"
            )
            return 0
        if latest_image.get("store", None) == helpers.CENTRALIZED_STORE:
            print(
                f"The latest {distro}-{release} {variant} image has been released.",
                file=sys.stderr
            )
            return 0
        source_image = latest_image
        print('found latest image {} ({}) to publish'.format(
            source_image['name'], source_image['id']))
    else:
        print('must provide --latest or --image', file=sys.stderr)
        return 1

    image_production_name = production_name(image=source_image)

    # publish image
    new_image = copy_image(
        auth_sessions[args.from_site], centralized_auth_session, source_image['id']
    )

    # rename old image at centralized object store
    glance = chi.glance(session=centralized_auth_session)
    named_images = list(glance.images.list(filters={
        'name': image_production_name,
        'owner': auth_data['auths'][args.from_site]['OS_PROJECT_ID'],
        'visibility': 'public',
        'store': helpers.CENTRALIZED_STORE}
    ))
    if len(named_images) == 1:
        archive_image(centralized_auth_session, auth_data['auths'][args.from_site]
                      ['OS_PROJECT_ID'], named_images[0]['id'])
    elif len(named_images) > 1:
        raise RuntimeError(
            'multiple images with the name "{}"'
            .format(image_production_name))
    elif len(named_images) < 1:
        # do nothing
        print(f"no public production images {image_production_name} found on site {helpers.CENTRALIZED_STORE_SITE}")

    # rename new image at centralized object store
    glance = chi.glance(session=centralized_auth_session)
    glance.images.update(new_image['id'],
                         name=image_production_name,
                         visibility='public',
                         )

    # delete tmp image
    print('delete tmp image {} from site {}'.format(source_image['id'], args.from_site))
    glance = chi.glance(session=auth_sessions[args.from_site])
    glance.images.delete(source_image['id'])

    if args.notify:
        relay, to_emails = args.notify
        print(f"sending emails to {to_emails}")
        helpers.send_notification_mail(
            relay,
            "no-reply@chameleoncloud.org",
            to_emails.split(","),
            new_image
        )


if __name__ == '__main__':
    sys.exit(main(sys.argv))
