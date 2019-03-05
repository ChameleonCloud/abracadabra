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
import argparse
import json
import operator
import os
import shlex
import subprocess
import sys
import tempfile
from urllib.parse import urlparse

from hammers.osapi import Auth
from hammers.osrest import glance


BASE_NAME = {
    'ubuntu-trusty': 'Ubuntu14.04',
    'ubuntu-xenial': 'Ubuntu16.04',
    'ubuntu-bionic': 'Ubuntu18.04',
    'centos7': 'CentOS7',
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
SITE_AUTH_HOSTS = {
    'kvm': 'openstack.tacc.chameleoncloud.org',
    'tacc': 'chi.tacc.chameleoncloud.org',
    'uc': 'chi.uc.chameleoncloud.org',
    'dev': 'dev.tacc.chameleoncloud.org',
}
VARIANT_NAME = {
    'base': '',
    'gpu': 'CUDA',
    'fpga': 'FPGA',
    'arm64': 'ARM64'
}
CUDA_VERSION = {
    'cuda8': '8',
    'cuda9': '9',
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
                
    # if os and variant provided, use the provided value first; otherwise, consider the values read from image
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
        variant = '{}{}'.format(variant, CUDA_VERSION[cuda_version])
    
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


def copy_image(source_auth, target_auths, source_image_id):
    source_image = glance.image(source_auth, id=source_image_id)
    extra = extract_extra_properties(source_image)

    public = source_image['visibility'] == 'public'

    new_images = {}
    with tempfile.TemporaryDirectory() as tempdir:
        img_file = os.path.join(tempdir, 'image')

        curl_download = glance.image_download_curl(source_auth, source_image['id'], filepath=img_file)
        proc = subprocess.run(shlex.split(curl_download), check=True)

        for site, target_auth in target_auths.items():
            # to create a new image, need to create an empty image first and upload image file to the "file" url.
            # the process will cause re-run problem.
            # if creating new empty image succeeds, but uploading file fails, there will be an empty image 
            # with "queued" status. When re-run, our program will pick the empty image as the latest
            # image. To avoid this, we need to delete the queued image if uploading step fails. 
            new_image = glance.image_create(target_auth, source_image['name'], public=public, extra=extra)
            try:
                curl_upload = glance.image_upload_curl(target_auth, new_image['id'], img_file)
                proc = subprocess.run(shlex.split(curl_upload), check=True)
            except Exception as e:
                # will raise exception if deleting fails; in this case, please manually delete the empty image!
                glance.image_delete(target_auth, new_image['id'])
                raise e
                
            new_image_full = glance.image(target_auth, id=new_image['id'])
            if new_image_full['checksum'] != source_image['checksum']:
                raise RuntimeError('checksum mismatch')

            new_images[site] = new_image_full

    return new_images


def archive_image(auth, owner, image):
    '''
    auth : Auth object
        Authentication/authorization object indicating site to target.
    image : str or dict
        ID of image to archive or dictionary with contents. New name autogenerated based on metadata.
    '''
    if isinstance(image, str):
        image = glance.image(auth, id=image)

    new_name_base = archival_name(image=image)
    new_name = new_name_base
    subversion = 0
    while True:
        name_collisions = glance.images(auth, query={
            'name': new_name,
            'owner': owner,
            'visibility': 'public',
        })
        if len(name_collisions) == 0:
            break
        subversion += 1
        new_name = '{}.{}'.format(new_name_base, subversion)

    print('renaming image {} ({}) to {}'.format(image['name'], image['id'], new_name))
    glance.image_properties(auth, image['id'], replace={'name': new_name})


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
    parser.add_argument('-t', '--target', type=str, action='append', choices=SITE_AUTH_HOSTS,
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

    auths = {}
    for site, auth_info in auth_data['auths'].items():
        auths[site] = Auth(auth_info)

    if args.image:
        source_site, source_id = args.image
        source_image = glance.image(auths[source_site], id=source_id)
        print('found specified image {} ({}) to publish'.format(source_image['name'], source_id))
    elif args.latest:
        source_site, distro, variant = args.latest
        query = {
            'build-os': distro,
            'status': 'active', # to prevent "queued" images, though we handle the situation in "copy_image" function
        }
        cuda_version = None
        if variant.startswith('gpu'):
            variant_cuda = variant.split('-')
            variant = variant_cuda[0]
            cuda_version = variant_cuda[1]
            query['build-variant'] = variant
            query['build-cuda-version'] = cuda_version
        else:
            query['build-variant'] = variant

        matching_images = glance.images(auths[source_site], query=query)
        matching_images.sort(reverse=True, key=operator.itemgetter('created_at'))
        latest_image = matching_images[0]
        if latest_image['name'] == production_name(os=distro, variant=variant, cuda_version=cuda_version):
            print('latest image matching distro "{}", variant "{}" already has production name (released?)'
                  .format(distro, variant), file=sys.stderr)
            return 0
        source_image = latest_image
        source_id = source_image['id']
        print('found latest image {} ({}) to publish'.format(source_image['name'], source_id))
    else:
        print('must provide --latest or --image', file=sys.stderr)
        return 1

    image_production_name = production_name(source_image)

    target_auths = {site: auths[site] for site in args.target}

    # filter eligible copy targets
    ineligible = []
    for site, auth in target_auths.items():
        images = glance.images(auth, query={
            'name': image_production_name,
            'visibility': 'public',
        })
        images.sort(reverse=True, key=operator.itemgetter('created_at'))
        if len(images) > 0 and images[0]['checksum'] == source_image['checksum']:
            print('skipping site "{}", already has production-named image with the same checksum ({})'
                  .format(site, source_image['checksum']))
            ineligible.append(site)
    for site in ineligible: # can I modify keys while iterating? forgot
        target_auths.pop(site)

    if not target_auths:
        print('no targets left, stopping.', file=sys.stderr)
        return 0

    # copy the images
    new_images = copy_image(auths[source_site], target_auths, source_id)

    # rename old
    for site, auth in target_auths.items():
        named_images = glance.images(auth, query={
            'name': image_production_name,
            'owner': auth_data['auths'][site]['OS_PROJECT_ID'],
            'visibility': 'public',
        })
        if len(named_images) == 1:
            archive_image(auth, auth_data['auths'][site]['OS_PROJECT_ID'], named_images[0]['id'])
        elif len(named_images) > 1:
            raise RuntimeError('multiple images with the name "{}"'.format(image_production_name))
        elif len(named_images) < 1:
            # do nothing
            print('no public production images "{}" found on site "{}"'.format(image_production_name, site))
            continue

    # rename new
    for site, auth in target_auths.items():
        glance.image_properties(auth, new_images[site]['id'], replace={
            'name': image_production_name,
            'visibility': 'public',
        })
        
    # delete tmp image
    print('delete tmp image {} from site {}'.format(source_id, source_site))
    glance.image_delete(auths[source_site], source_id)


if __name__ == '__main__':
    sys.exit(main(sys.argv))
