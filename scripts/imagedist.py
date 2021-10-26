#!/usr/bin/env python
'''
Distribute images to the various infrastructures.

JSON auth file should be of format:

    {"auths": {"<site1>": {"<OS_var>": "<value>", ...}, ...}}

The source image will be copied to the other two infrastructures using
cURL, then the old (currently active) production images will be renamed,
then the new images renamed in their stead.

After doing this, update the IDs on the portal catalog
(https://www.chameleoncloud.org/appliances/)
'''
import operator
import os
import sys

sys.path.append("..")

import argparse
import chi
import json
import shlex
import subprocess
import tempfile
from urllib.parse import urlparse
from utils import helpers


BASE_NAME = {
    'ubuntu-bionic': 'Ubuntu18.04',
    'ubuntu-focal': 'Ubuntu20.04',
    'centos7': 'CentOS7',
    'centos8': 'CentOS8',
}
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
VARIANT_NAME = {
    'base': '',
    'gpu': 'CUDA',
    'fpga': 'FPGA',
    'arm64': 'ARM64'
}


def production_name(image=None, os=None, variant=None, cuda_version=None):
    os_from_image = None
    variant_from_image = None
    if image is not None:
        try:
            os_from_image = image['build-os']
            variant_from_image = image['build-variant']
        except KeyError:
            try:
                os_from_image = image['build_os']
                variant_from_image = image['build_variant']
            except KeyError:
                # do nothing
                pass

    # if os and variant provided, use the provided value first; otherwise,
    # consider the values read from image
    if os is None:
        os = os_from_image
    if variant is None:
        variant = variant_from_image

    if os is None or variant is None:
        raise ValueError('must provide image or os/variant')

    base = BASE_NAME[os]
    variant = VARIANT_NAME[variant]

    if variant == 'CUDA':
        if cuda_version is None:
            cuda_version = image['build-cuda-version']
        variant = '{}{}'.format(variant, cuda_version.replace('cuda', ''))

    var_delim = '-' if variant else ''
    return 'CC-{}{}{}'.format(base, var_delim, variant)


def archival_name(image=None, os=None, variant=None, cuda_version=None):
    build_os_base_image_revision = None
    try:
        build_os_base_image_revision = image['build-os-base-image-revision']
    except KeyError:
        build_os_base_image_revision = image['build_os_base_image_revision']

    if build_os_base_image_revision is None:
        raise ValueError('No build os base image revision found!')

    return '{}-{}'.format(production_name(image, os, variant, cuda_version), build_os_base_image_revision)


def extract_extra_properties(image):
    return {k: image[k] for k in image if k not in BASE_PROPS}


def copy_image(source_auth_session, target_auths, source_image_id):
    glance = chi.glance(session=source_auth_session)
    source_image = glance.images.get(source_image_id)
    extra = extract_extra_properties(source_image)

    new_images = {}
    with tempfile.TemporaryDirectory() as tempdir:
        img_file = os.path.join(tempdir, 'image')

        curl_download = helpers.image_download_curl(
            source_auth_session.get_token(),
            source_auth_session.get_endpoint(service_type="image"),
            source_image['id'], filepath=img_file)
        proc = subprocess.run(shlex.split(curl_download), check=True)

        for site, target_auth_session in target_auths.items():
            # to create a new image, need to create an empty image first and upload image file to the "file" url.
            # the process will cause re-run problem.
            # if creating new empty image succeeds, but uploading file fails, there will be an empty image
            # with "queued" status. When re-run, our program will pick the empty image as the latest
            # image. To avoid this, we need to delete the queued image if
            # uploading step fails.
            glance_target = chi.glance(session=target_auth_session)
            disk_format = source_image['disk_format']
            if site == 'kvm':
                list_keys = list(extra.keys())
                for k in list_keys:
                    if k.startswith('os_'):
                        extra.pop(k)
                converted_img_file = os.path.join(tempdir, 'raw_image')
                disk_format = 'raw'
                command = 'qemu-img convert -f qcow2 -O {} {} {}'.format(
                    disk_format, img_file, converted_img_file)
                proc = subprocess.run(shlex.split(command), check=True)
                img_file = converted_img_file
            new_image = glance_target.images.create(
                name=source_image['name'],
                visibility=source_image['visibility'],
                disk_format=disk_format,
                container_format='bare',
                **extra)
            try:
                curl_upload = helpers.image_upload_curl(
                    target_auth_session.get_token(),
                    target_auth_session.get_endpoint(service_type="image"),
                    new_image['id'], img_file)
                proc = subprocess.run(shlex.split(curl_upload), check=True)
            except Exception as e:
                # will raise exception if deleting fails; in this case, please
                # manually delete the empty image!
                glance_target.images.delete(new_image['id'])
                raise e

            new_image_full = glance_target.images.get(new_image['id'])
            if site != 'kvm' and new_image_full['checksum'] != source_image['checksum']:
                # skip checksum check for kvm site
                raise RuntimeError('checksum mismatch')

            new_images[site] = new_image_full

    return new_images


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

    new_name_base = archival_name(image=image)
    new_name = new_name_base
    subversion = 0
    while True:
        name_collisions = list(glance.images.list(filters={
            'name': new_name,
            'owner': owner,
            'visibility': 'public',
        }))
        if len(name_collisions) == 0:
            break
        subversion += 1
        new_name = '{}.{}'.format(new_name_base, subversion)

    print('renaming image {} ({}) to {}'.format(
        image['name'], image['id'], new_name))
    glance.images.update(image['id'], name=new_name)


# def release_image(auth, image):
#     '''
#     auth : Auth object
#         Authentication/authorization object indicating site to target.
#     image : str or dict
#         ID of image to archive or dictionary with contents. New name autogenerated based on metadata.
#     '''
#     if isinstance(image, str):
#         image = glance.image(auth, id=image)

#     new_name = production_name(image=image)


def main(argv=None):
    if argv is None:
        argv = sys.argv

    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # auth.add_arguments(parser)
    parser.add_argument('auth_jsons', type=str,
                        help='File with auth info in JSON format for all sites.')
    parser.add_argument('--latest', type=str, nargs=3, metavar=('site', 'distro', 'variant'),
                        help='Publish latest tested image given 3 args: <source-site> <distro> <variant>')
    parser.add_argument('--image', type=str, nargs=2, metavar=('site', 'id'),
                        help='Site and ID of image to push around, separated by space: e.g. "uc 12345678-1234..."')
    parser.add_argument('-t', '--target', type=str, action='append',
                        help='Specify once for each target site to push said image to')
    # parser.add_argument('new_name' type=str,
    #     help='New name of the image')
    # parser.add_argument('--public', action='store_true',
    #     help='Mark images as public')

    args = parser.parse_args(argv[1:])
    # session, rc = auth.session_from_args(args, rc=True)

    # determine the site, make other RCs for the others...
    with open(args.auth_jsons) as f:
        auth_data = json.load(f)

    if not args.target:
        print('no targets specified, stopping.', file=sys.stderr)
        return 0

    auth_sessions = {}
    for site, auth_info in auth_data['auths'].items():
        try:
            auth_sessions[site] = helpers.get_auth_session_from_rc(auth_info)
        except Exception as e:
            if site == 'dev':
                print('dev authentication failed!')
            else:
                raise e

    if args.image:
        source_site, source_id = args.image
        glance_source = chi.glance(session=auth_sessions[source_site])
        source_image = glance_source.get(source_id)
        print('found specified image {} ({}) to publish'.format(
            source_image['name'], source_id))
    elif args.latest:
        source_site, distro, variant = args.latest
        glance_source = chi.glance(session=auth_sessions[source_site])
        query = {
            'build-os': distro,
            # to prevent "queued" images, though we handle the situation in
            # "copy_image" function
            'status': 'active',
            'build-variant': variant,
        }
        cuda_version = None
        if variant.startswith('gpu'):
            variant_cuda = variant.split('-')
            variant = variant_cuda[0]
            cuda_version = variant_cuda[1]
            query['build-variant'] = variant
            query['build-cuda-version'] = cuda_version

        matching_images = list(glance_source.images.list(filters=query))
        matching_images.sort(
            reverse=True, key=operator.itemgetter('created_at'))
        latest_image = matching_images[0]
        if latest_image['name'] == production_name(os=distro, variant=variant,
                                                   cuda_version=cuda_version):
            print('latest image matching distro "{}", variant "{}" already '
                  'has production name (released?)'
                  .format(distro, variant), file=sys.stderr)
            return 0
        source_image = latest_image
        source_id = source_image['id']
        print('found latest image {} ({}) to publish'.format(
            source_image['name'], source_id))
    else:
        print('must provide --latest or --image', file=sys.stderr)
        return 1

    image_production_name = production_name(source_image)

    target_auth_sessions = {site: auth_sessions[site] for site in args.target}

    # filter eligible copy targets
    ineligible = []
    for site, auth_session in target_auth_sessions.items():
        glance_target = chi.glance(session=auth_session)
        images = list(glance_target.images.list(filters={
            'name': image_production_name,
            'visibility': 'public'}
        ))
        images.sort(reverse=True, key=operator.itemgetter('created_at'))
        if len(images) > 0 and \
                images[0]['checksum'] == source_image['checksum']:
            print('skipping site "{}", already has production-named '
                  'image with the same checksum ({})'
                  .format(site, source_image['checksum']))
            ineligible.append(site)
    for site in ineligible:  # can I modify keys while iterating? forgot
        target_auth_sessions.pop(site)

    if not target_auth_sessions:
        print('no targets left, stopping.', file=sys.stderr)
        return 0

    # copy the images
    new_images = copy_image(
        auth_sessions[source_site], target_auth_sessions, source_id)

    # rename old
    for site, auth_session in target_auth_sessions.items():
        glance = chi.glance(session=auth_session)
        named_images = list(glance.images.list(filters={
            'name': image_production_name,
            'owner': auth_data['auths'][site]['OS_PROJECT_ID'],
            'visibility': 'public'}
        ))
        if len(named_images) == 1:
            archive_image(auth_session, auth_data['auths'][site]
                          ['OS_PROJECT_ID'], named_images[0]['id'])
        elif len(named_images) > 1:
            raise RuntimeError(
                'multiple images with the name "{}"'
                .format(image_production_name))
        elif len(named_images) < 1:
            # do nothing
            print('no public production images "{}" found on site "{}"'.format(
                image_production_name, site))
            continue

    # rename new
    for site, auth_session in target_auth_sessions.items():
        glance = chi.glance(session=auth_session)
        glance.images.update(new_images[site]['id'],
                             name=image_production_name,
                             visibility='public'
                             )

    # delete tmp image
    print('delete tmp image {} from site {}'.format(source_id, source_site))
    glance = chi.glance(session=auth_sessions[source_site])
    glance.images.delete(source_id)


if __name__ == '__main__':
    sys.exit(main(sys.argv))
