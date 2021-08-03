'''
Compare the latest released Chameleon appliance with the latest base image.
Notify if Chameleon appliance needs update.
'''
import os
import sys

sys.path.append("..")

import argparse
import chi
import json
import shlex
import subprocess
import tempfile
from utils import helpers
from utils import jenkinshelper
from utils import whatsnew

from . import imagedist

PRODUCTION_NAMES_AND_SITES = {
    'CC-CentOS7': {
        'sites': ['uc', 'tacc'],
        'os': 'centos7',
        'resource_type': 'compute_haswell',
        'build': 'base'
    },
    'CC-CentOS7 KVM': {
        'sites': ['kvm'],
        'os': 'centos7',
        'resource_type': 'compute_haswell',
        'build': 'base'
    },
    'CC-CentOS8': {
        'sites': ['uc', 'tacc'],
        'os': 'centos8',
        'resource_type': 'compute_haswell',
        'build': 'base'
    },
    'CC-CentOS8 KVM': {
        'sites': ['kvm'],
        'os': 'centos8',
        'resource_type': 'compute_haswell',
        'build': 'base'
    },
    'CC-CentOS7-CUDA11': {
        'sites': ['uc', 'tacc'],
        'os': 'centos7',
        'resource_type': 'gpu_p100',
        'build': 'gpu'
    },
    'CC-CentOS8-CUDA11': {
        'sites': ['uc', 'tacc'],
        'os': 'centos8',
        'resource_type': 'gpu_p100',
        'build': 'gpu'},
    'CC-CentOS7-FPGA UC': {
        'sites': ['uc'],
        'os': 'centos7',
        'resource_type': 'fpga',
        'build': 'fpga'},
    'CC-CentOS7-FPGA TACC': {
        'sites': ['tacc'],
        'os': 'centos7',
        'resource_type': 'fpga',
        'build': 'fpga'
    },
    'CC-Ubuntu18.04': {
        'sites': ['uc', 'tacc'],
        'os': 'ubuntu-bionic',
        'resource_type': 'compute_haswell',
        'build': 'base'
    },
    'CC-Ubuntu18.04 KVM': {
        'sites': ['kvm'],
        'os': 'ubuntu-bionic',
        'resource_type': 'compute_haswell',
        'build': 'base'
    },
    'CC-Ubuntu18.04-CUDA11': {
        'sites': ['uc', 'tacc'],
        'os': 'ubuntu-bionic',
        'resource_type': 'gpu_p100',
        'build': 'gpu'
    },
    'CC-Ubuntu20.04': {
        'sites': ['uc', 'tacc'],
        'os': 'ubuntu-focal',
        'resource_type': 'compute_haswell',
        'build': 'base'
    },
    'CC-Ubuntu20.04 KVM': {
        'sites': ['kvm'],
        'os': 'ubuntu-focal',
        'resource_type': 'compute_haswell',
        'build': 'base'
    },
    'CC-Ubuntu20.04-CUDA11': {
        'sites': ['uc', 'tacc'],
        'os': 'ubuntu-focal',
        'resource_type': 'gpu_p100',
        'build': 'gpu'
    }
}

ACTION_CODE = {0: 'UP-TO-DATE',
               1: 'SYNC',
               2: 'UPDATE'}


def get_required_action(auth_data, production_name):
    site_spec = production_name.split(' ')
    actual_production_name = production_name
    if len(site_spec) == 1:
        pass
    elif len(site_spec) == 2:
        actual_production_name = site_spec[0]
    else:
        raise ValueError('Unable to process image {}'.format(production_name))

    rev_at_site = {}
    for site in PRODUCTION_NAMES_AND_SITES[production_name]['sites']:
        glance = chi.glance(
            session=helpers.get_auth_session_from_rc(auth_data[site]))

        images = list(glance.images.list(filters={
            'name': actual_production_name, 'visibility': 'public'}))

        if len(images) > 1:
            raise ValueError(
                'More than one {} images found at {} site!'.format(
                    actual_production_name, site))
        elif len(images) == 0:
            # first time deployment
            rev_at_site[site] = {
                'build-os-base-image-revision': None, 'id': None}
        else:
            image_revision = images[0]['build-os-base-image-revision']
            image_id = images[0]['id']
            rev_at_site[site] = {
                'build-os-base-image-revision': image_revision,
                'id': image_id}

    latest_base_release = latest_base(
        PRODUCTION_NAMES_AND_SITES[production_name]['os'])
    latest_base_release_rev = latest_base_release['revision']

    code = None
    revisions = [rev['build-os-base-image-revision']
                 for rev in rev_at_site.values()]
    detail = {'message': None, 'latest_base_release': latest_base_release_rev,
              'site_detail': rev_at_site}
    if latest_base_release_rev in revisions:
        if len(set(revisions)) == 1:
            code = 0
            detail['message'] = 'Appliance up to date! Nothing to do.'
        else:
            code = 1
            detail['message'] = 'Sync among sites required!'
    else:
        code = 2
        detail['message'] = 'Update required!'

    return code, detail


def latest_base(os_name):
    if os_name.startswith('centos'):
        return whatsnew.newest_centos(int(os_name[6:]))
    elif os_name.startswith('ubuntu-'):
        return whatsnew.newest_ubuntu(os_name[7:])
    else:
        raise ValueError('Unknown os {}'.format(os))


def reserve_resource_for_release(jenkins_location, production_name, detail):
    booking_site = None
    if 'tacc' in detail['site_detail'].keys():
        booking_site = 'tacc'
    elif 'uc' in detail['site_detail'].keys():
        booking_site = 'uc'
    elif 'kvm' in detail['site_detail'].keys():
        booking_site = 'tacc'
    else:
        raise ValueError('Not able to book resource for release!')

    builder_name = production_name.lower().replace(' ', '-') + '-builder'
    build_config_file = jenkins_location + '/' + \
        jenkinshelper.JENKINS_JOB_CONFIG_FILE.format(job_name=builder_name)
    node_type = PRODUCTION_NAMES_AND_SITES[production_name]['resource_type']
    service_openrc = jenkins_location + '/' + \
        jenkinshelper.JENKINS_SERVICE_ACCOUNT_CREDENTIAL_FILE.format(
            site=booking_site)
    cuda_export = ''
    if PRODUCTION_NAMES_AND_SITES[production_name]['build'] == 'gpu':
        cuda_version = production_name[production_name.index('CUDA'):].lower()
        cuda_export = 'export CUDA_VERSION={cuda_version}'.format(
            cuda_version=cuda_version)
    build_os = PRODUCTION_NAMES_AND_SITES[production_name]['os']
    build_script = None
    extra = ''
    if 'centos' in build_os:
        # centos
        build_script = 'do_build_centos.sh'
        params = PRODUCTION_NAMES_AND_SITES[production_name]['build']
        extra = 'export CENTOS_VERSION={}'.format(
            build_os.replace('centos', ''))
    elif 'ubuntu' in build_os:
        # ubuntu
        build_script = 'do_build_ubuntu.sh'
        build_os = build_os.split('-')
        params = '{} {}'.format(
            build_os[1], PRODUCTION_NAMES_AND_SITES[production_name]['build'])

    command_list = ['#!/bin/bash',
                    'rm build.log',
                    'source {service_openrc}'.format(
                        service_openrc=service_openrc),
                    'export SSH_KEY_FILE={key_file}'.format(
                        key_file=jenkins_location + '/ssh.key'),
                    'export SSH_KEY_NAME={key_name}'.format(
                        key_name=jenkinshelper.SITE_KEY_NAME_MAP[booking_site]),
                    'export EXISTING_LEASE={lease_id}',
                    'export NODE_TYPE={node_type}'.format(node_type=node_type),
                    extra,
                    cuda_export,
                    'cd scripts',
                    'sleep $[ ( $RANDOM % 100 ) + 1 ]s',
                    './{build_script} {params}'.format(
                        build_script=build_script,
                        params=params)
                    ]

    command = '\n'.join(command_list)

    jenkinshelper.update_env_variables_from_file(service_openrc)
    reserve_resource_args = {'booking_site': booking_site,
                             'node_type': node_type,
                             'lease_name_prefix': 'appliance-auto-release-',
                             'job_name': builder_name,
                             'job_config_file': build_config_file,
                             'lease_duration_in_hour': 6,
                             'searching_feq_in_min': 60,
                             'exec_command': command,
                             'jenkins_location': jenkins_location}

    if 'kvm' in detail['site_detail'].keys():
        command_list.insert(6, 'export KVM=true')
        kvm_command = '\n'.join(command_list)
        jenkinshelper.update_env_variables_from_file(service_openrc)
        reserve_resource_args['job_config_file'] = jenkins_location + '/' + \
            jenkinshelper.JENKINS_JOB_CONFIG_FILE.format(
                job_name=reserve_resource_args['job_name'])
        reserve_resource_args['exec_command'] = kvm_command

    jenkinshelper.reserve_resource(**reserve_resource_args)


def do_sync(auth_data, production_name, detail):
    production_name = production_name.split(' ')[0]
    from_site = None
    to_site = []
    for site in sorted(list(detail['site_detail'].keys())):
        if detail['site_detail'][site] == detail['latest_base_release']:
            from_site = site
        else:
            to_site.append(site)

    # get image and image properties from from_site
    glance_from_site = chi.glance(
        session=helpers.get_auth_session_from_rc(auth_data[from_site]))
    source_image = glance_from_site.images.get(
        detail['site_detail'][from_site]['id'])
    extra = imagedist.extract_extra_properties(source_image)

    for dest_site in to_site:
        # rename images at to_site
        glance_to_site = chi.glance(
            session=helpers.get_auth_session_from_rc(auth_data[to_site]))
        imagedist.archive_image(
            glance_to_site, detail['site_detail'][dest_site]['id'])

        # copy image to to_sites
        new_image = glance_to_site.images.create(
            name=source_image['name'], public=True, extra=extra)
        glance_to_site.images.upload(
            image_id=new_image['id'],
            image_data=glance_from_site.data(source_image['id']))

        new_image_full = glance_to_site.images.get(new_image['id'])
        if new_image_full['checksum'] != source_image['checksum']:
            raise RuntimeError('checksum mismatch')

    print('Sync finished successfully!')


def main(argv=None):
    if argv is None:
        argv = sys.argv

    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument('jenkins_jobs_location', type=str,
                        help='Jenkins jobs location')
    parser.add_argument('auth_json', type=str,
                        help=("File with auth info in JSON format "
                              "for all sites."))

    parser.add_argument('--skip', type=str,
                        help='skip appliances; comma separated', default=None)

    args = parser.parse_args(argv[1:])

    skip_appliances = []
    if args.skip:
        skip_appliances = args.skip.split(',')

    with open(args.auth_json) as f:
        auth_data = json.load(f)

    for image_name in [item for item in PRODUCTION_NAMES_AND_SITES.keys()
                       if item not in skip_appliances]:
        action_code, detail = get_required_action(
            auth_data['auths'], image_name)
        print('---------{}---------'.format(image_name))
        print(json.dumps(detail, indent=4, sort_keys=True))
        if action_code == 1:
            # sync among sites
            do_sync(auth_data['auths'], image_name, detail)
        if action_code == 2:
            # prepare for release
            reserve_resource_for_release(
                args.jenkins_jobs_location, image_name, detail)


if __name__ == '__main__':
    sys.exit(main(sys.argv))
