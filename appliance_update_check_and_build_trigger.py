'''
Compare the latest released Chameleon appliance with the latest base image.
Notify if Chameleon appliance needs update.
'''
import argparse
import datetime
import json
import os
import requests
import shlex
import subprocess
import sys
import tempfile
import traceback
import xml.etree.ElementTree as et

from croniter import croniter
from dateutil import tz
from blazarclient import exception as blazarexception
from urllib import parse as urlparse

from ccmanage import lease as ccmanagelease
from ccmanage import auth as ccmanageauth
from hammers.osapi import Auth
from hammers.osapi import load_osrc
from hammers.osrest import glance

import imagedist
import whatsnew

PRODUCTION_NAMES_AND_SITES = {'CC-CentOS7': {'sites': ['uc', 'tacc', 'kvm'], 'os': 'centos7', 'resource_type': 'compute_haswell'},
                              'CC-CentOS7-CUDA9': {'sites': ['tacc'], 'os': 'centos7', 'resource_type': 'gpu_p100'},
                              'CC-CentOS7-FPGA UC': {'sites': ['uc'], 'os': 'centos7', 'resource_type': 'fpga'},
                              'CC-CentOS7-FPGA TACC': {'sites': ['tacc'], 'os': 'centos7', 'resource_type': 'fpga'},
                              'CC-Ubuntu14.04': {'sites': ['uc', 'tacc', 'kvm'], 'os': 'ubuntu-trusty', 'resource_type': 'compute_haswell'},
                              'CC-Ubuntu16.04': {'sites': ['uc', 'tacc', 'kvm'], 'os': 'ubuntu-xenial', 'resource_type': 'compute_haswell'},
                              'CC-Ubuntu16.04-CUDA8': {'sites': ['tacc'], 'os': 'ubuntu-xenial', 'resource_type': 'gpu_p100'},
                              'CC-Ubuntu16.04-CUDA9': {'sites': ['tacc'], 'os': 'ubuntu-xenial', 'resource_type': 'gpu_p100'},
                              'CC-Ubuntu16.04-ARM64': {'sites': ['tacc'], 'os': 'ubuntu-xenial', 'resource_type': 'arm64'}
                              }

ACTION_CODE = {0: 'UP-TO-DATE',
               1: 'SYNC',
               2: 'UPDATE'}

JENKINS_BUILD_CONFIG_FILE = '/var/lib/jenkins/jobs/{builder_name}/config.xml'
JENKINS_CCTEST_CREDENTIAL_FILE = '/var/lib/jenkins/Chameleon-{site}-cctest.sh'
JENKINS_URL = 'https://{username}:{password}@jenkins.chameleoncloud.org'
JENKINS_RELOAD_JOB_URL = JENKINS_URL + '/view/appliances/job/{builder_name}/reload'
ADVANCED_RESERVATION_MAX_DAY = 15

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
        auth = Auth(auth_data[site])
        
        images = glance.images(auth, {'name': actual_production_name})
    
        if len(images) > 1:
            raise ValueError('More than one {} images found at {} site!'.format(actual_production_name, site))
        elif len(images) == 0:
            # first time deployment
            rev_at_site[site] = {'build-os-base-image-revision': None, 'id': None}
        else:
            rev_at_site[site] = {'build-os-base-image-revision': images[0]['build-os-base-image-revision'], 'id': images[0]['id']}
      
    latest_base_release = latest_base(PRODUCTION_NAMES_AND_SITES[production_name]['os'])
    latest_base_release_rev = latest_base_release['revision']
    
    code = None
    revisions = [rev['build-os-base-image-revision'] for rev in rev_at_site.values()]
    detail = {'message': None, 'latest_base_release': latest_base_release_rev, 'site_detail': rev_at_site}
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

def latest_base(os):
    if os == 'centos7':
        return whatsnew.centos7()
    elif os == 'ubuntu-xenial':
        return whatsnew.newest_ubuntu('xenial')
    elif os == 'ubuntu-trusty':
        return whatsnew.newest_ubuntu('trusty')
    else:
        raise ValueError('Unknown os {}'.format(os))
    
def update_env_variables_from_file(file):
    with open(file, 'r') as f:
        for line in f:
            if 'export' not in line:
                continue
            if line.startswith('#'):
                continue
            key, value = line.replace('export ', '', 1).strip().split('=', 1)
            os.environ[key] = value.replace('"', '')
    
def reserve_resource_for_release(production_name, detail):
    booking_site = None
    if 'tacc' in detail['site_detail'].keys():
        booking_site = 'tacc'
    elif 'uc' in detail['site_detail'].keys():
        booking_site = 'uc'
    else:
        raise ValueError('Site issue occurs! Not able to book resource for release!')
    update_env_variables_from_file(JENKINS_CCTEST_CREDENTIAL_FILE.format(site=booking_site))
    now = datetime.datetime.now(tz=tz.tzutc())
    # check if there already exists a scheduled Jenkins build
    builder_name = production_name.lower().replace(' ', '-') + '-builder'
    build_config_file = JENKINS_BUILD_CONFIG_FILE.format(builder_name=builder_name)
    config_xml_tree = et.parse(build_config_file)
    
    cron_time = None
    for t in config_xml_tree.getroot().findall('triggers'):
        for tt in t.findall('hudson.triggers.TimerTrigger'):
            for s in tt.findall('spec'):
                cron_time = s.text
    
    if cron_time:
        iter = croniter(cron_time, now)
        if iter.get_next(datetime.datetime) <= now + datetime.timedelta(days=ADVANCED_RESERVATION_MAX_DAY):
            print('A reservation exists and waits for release; no need to reset.')
            return
    
    # try booking every 1 hour with max 15 days
    blazarclient = ccmanagelease.BlazarClient('1', ccmanageauth.session_from_args())
    reservation_args = {'name': 'appliance-auto-release-{}'.format(production_name.split(' ')[0].replace('.', '').lower()),
                        'start': None,
                        'end': None,
                        'reservations': [{'resource_type': 'physical:host',
                                         'resource_properties': json.dumps(['=', '$node_type', PRODUCTION_NAMES_AND_SITES[production_name]['resource_type']]),
                                         'hypervisor_properties': '',
                                         'min': 1,
                                         'max': 1}],
                        'events': []}
    start = now + datetime.timedelta(seconds=70)
    max_try_end = start + datetime.timedelta(days=ADVANCED_RESERVATION_MAX_DAY)
    lease = None
    while start < max_try_end:
        reservation_args['start'] = start.strftime(ccmanagelease.BLAZAR_TIME_FORMAT)
        reservation_args['end'] = (start + datetime.timedelta(hours=6)).strftime(ccmanagelease.BLAZAR_TIME_FORMAT)
        try:
            lease = blazarclient.lease.create(**reservation_args)
            break
        except blazarexception.BlazarClientException as bce:
            if 'Not enough hosts available' in str(bce):
                start = start + datetime.timedelta(hours=1)
            else:
                traceback.print_exc()
                raise bce
    if lease:
        lease_id = lease['id']
        # release will start 15 minutes later
        release_start_time = (start + datetime.timedelta(minutes=15)).astimezone(tz.gettz('America/Chicago'))
        cron_time = [release_start_time.minute, release_start_time.hour, release_start_time.day, release_start_time.month, '*']
        # schedule Jenkins build
        for t in config_xml_tree.getroot().findall('triggers'):
            for child in t:
                t.remove(child)
            trigger_element = et.Element('hudson.triggers.TimerTrigger')
            trigger_spec_element = et.Element('spec')
            trigger_spec_element.text = ' '.join(str(x) for x in cron_time)
            trigger_element.append(trigger_spec_element)
            t.append(trigger_element)
        # replace lease id
        for b in config_xml_tree.getroot().findall('builders'):
            for shell in b.findall('hudson.tasks.Shell'):
                for command in shell.findall('command'):
                    new_lines = []
                    for line in command.text.split('\n'):
                        if line.startswith('export EXISTING_LEASE='):
                            line = 'export EXISTING_LEASE=' + lease_id
                        new_lines.append(line)
                    command.text = '\n'.join(new_lines)
        config_xml_tree.write(build_config_file)
        
        # jenkins reload configuration from disk
        # we have CSRF protection, so we need to get crumb token first before reload
        jenkins_url = JENKINS_URL.format(username = os.environ['OS_USERNAME'], password = urlparse.quote(os.environ['OS_PASSWORD']))
        crumb = requests.get('{jenkins_url}/crumbIssuer/api/xml?xpath=concat(//crumbRequestField,":",//crumb)'.format(jenkins_url = jenkins_url)).text
        headers = {crumb.split(':')[0]: crumb.split(':')[1]}
        r = requests.post(JENKINS_RELOAD_JOB_URL.format(username = os.environ['OS_USERNAME'], 
                                                        password = urlparse.quote(os.environ['OS_PASSWORD']),
                                                        builder_name = builder_name),
                          headers = headers)
        
        print('Lease created with id {} at site {} and will start on {} (release will start 15 minutes later than lease start time.)'.format(lease_id, booking_site, start))
            
    else:
        raise RuntimeError('Reserve resource for releasing {} failed!'.format(production_name))
            

def do_sync(auth_data, production_name, detail):
    production_name = production_name.split(' ')[0]
    from_site = None
    to_site = []
    for site in detail['site_detail'].keys().sort():
        if detail['site_detail'][site] == detail['latest_base_release']:
            from_site = site
        else:
            to_site.append(site)
    
    # get image and image properties from from_site
    source_image = glance.image(Auth(auth_data[from_site]), id=detail['site_detail'][from_site]['id'])
    extra = imagedist.extract_extra_properties(source_image)
    
    with tempfile.TemporaryDirectory() as tempdir:
        # download image from from_site
        img_file = os.path.join(tempdir, 'image')
        curl_download = glance.image_download_curl(Auth(auth_data[from_site]), source_image['id'], filepath=img_file)
        proc = subprocess.run(shlex.split(curl_download), check=True)
        
        for dest_site in to_site:
            # rename images at to_site
            auth = Auth(auth_data[dest_site])
            imagedist.archive_image(auth, detail['site_detail'][dest_site]['id'])
        
            # copy image to to_sites
            new_image = glance.image_create(auth, source_image['name'], public=True, extra=extra)
            curl_upload = glance.image_upload_curl(auth, new_image['id'], img_file)
            proc = subprocess.run(shlex.split(curl_upload), check=True)

            new_image_full = glance.image(auth, id=new_image['id'])
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

    parser.add_argument('auth_json', type=str,
        help='File with auth info in JSON format for all sites.')
    
    args = parser.parse_args(argv[1:])

    with open(args.auth_json) as f:
        auth_data = json.load(f)

    for image_name in PRODUCTION_NAMES_AND_SITES.keys():
        action_code, detail = get_required_action(auth_data['auths'], image_name)
        print('---------{}---------'.format(image_name))
        print(json.dumps(detail, indent=4, sort_keys=True))
        if action_code == 1:
            # sync among sites
            do_sync(auth_data['auths'], image_name, detail)
        if action_code == 2:
            # prepare for release
            reserve_resource_for_release(image_name, detail)       

if __name__ == '__main__':
    sys.exit(main(sys.argv))
