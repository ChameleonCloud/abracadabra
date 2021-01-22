'''
helper functions for jenkins automatic processes
'''
import datetime
import json
import os
import requests
import traceback
import xml.etree.ElementTree as et

from croniter import croniter
from dateutil import tz
from blazarclient import exception as blazarexception
from urllib import parse as urlparse

from ccmanage import lease as ccmanagelease
from ccmanage import auth as ccmanageauth

JENKINS_JOB_CONFIG_FILE = 'jobs/{job_name}/config.xml'
JENKINS_CCTEST_CREDENTIAL_FILE = 'Chameleon-{site}-service-account.sh'
JENKINS_URL = 'https://{username}:{password}@jenkins.chameleoncloud.org'
JENKINS_RELOAD_JOB_URL = JENKINS_URL + '/view/appliances/job/{job_name}/reload'
ADVANCED_RESERVATION_MAX_DAY = 15
SITE_KEY_NAME_MAP = {'uc': 'default',
                     'tacc': 'jenkins'}

def update_env_variables_from_file(file):
    with open(file, 'r') as f:
        for line in f:
            if 'export' not in line:
                continue
            if line.startswith('#'):
                continue
            key, value = line.replace('export ', '', 1).strip().split('=', 1)
            os.environ[key] = value.replace('"', '')
            

def reserve_resource(booking_site, node_type, lease_name_prefix, job_name, job_config_file, lease_duration_in_hour, searching_feq_in_min, exec_command, node_count=1):
    now = datetime.datetime.now(tz=tz.tzutc())
    # check if there already exists a scheduled Jenkins build
    config_xml_tree = et.parse(job_config_file)
    
    cron_time = None
    for t in config_xml_tree.getroot().findall('triggers'):
        for tt in t.findall('hudson.triggers.TimerTrigger'):
            for s in tt.findall('spec'):
                cron_time = s.text
    
    if cron_time:
        iter = croniter(cron_time, now)
        if iter.get_next(datetime.datetime) <= now + datetime.timedelta(days=ADVANCED_RESERVATION_MAX_DAY):
            print('A reservation exists and waits for executing; no need to reset.')
            return
    
    # try booking every 30 minutes with max 15 days
    blazarclient = ccmanagelease.BlazarClient('1', ccmanageauth.session_from_args())
    reservation_args = {'name': lease_name_prefix + job_name,
                        'start': None,
                        'end': None,
                        'reservations': [{'resource_type': 'physical:host',
                                         'resource_properties': json.dumps(['=', '$node_type', node_type]),
                                         'hypervisor_properties': '',
                                         'min': node_count,
                                         'max': node_count}],
                        'events': []}
    start = now + datetime.timedelta(seconds=70)
    max_try_end = start + datetime.timedelta(days=ADVANCED_RESERVATION_MAX_DAY)
    lease = None
    while start < max_try_end:
        reservation_args['start'] = start.strftime(ccmanagelease.BLAZAR_TIME_FORMAT)
        reservation_args['end'] = (start + datetime.timedelta(hours=lease_duration_in_hour)).strftime(ccmanagelease.BLAZAR_TIME_FORMAT)
        try:
            lease = blazarclient.lease.create(**reservation_args)
            break
        except blazarexception.BlazarClientException as bce:
            if 'Not enough hosts available' in str(bce):
                start = start + datetime.timedelta(minutes=searching_feq_in_min)
            else:
                traceback.print_exc()
                raise bce
    if lease:
        lease_id = lease['id']
        # release will start 10 minutes later
        release_start_time = (start + datetime.timedelta(minutes=10)).astimezone(tz.gettz('America/Chicago'))
        cron_time = [release_start_time.minute, release_start_time.hour, release_start_time.day, release_start_time.month, '*']
        # schedule Jenkins test
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
                    command.text = exec_command.format(lease_id=lease_id)
        config_xml_tree.write(job_config_file)
        
        # jenkins reload configuration from disk
        # we have CSRF protection, so we need to get crumb token first before reload
        # crumbs are only valid within a created web session, see https://github.com/spinnaker/spinnaker/issues/2067 and https://github.com/spinnaker/spinnaker.github.io/pull/1512
        jenkins_url = JENKINS_URL.format(username = os.environ['OS_USERNAME'], password = urlparse.quote(os.environ['OS_PASSWORD']))
        sess = requests.Session()
        crumb = sess.get('{jenkins_url}/crumbIssuer/api/xml?xpath=concat(//crumbRequestField,":",//crumb)'.format(jenkins_url = jenkins_url)).text
        headers = {crumb.split(':')[0]: crumb.split(':')[1]}
        r = sess.post(JENKINS_RELOAD_JOB_URL.format(username = os.environ['OS_USERNAME'], 
                                                    password = urlparse.quote(os.environ['OS_PASSWORD']),
                                                    job_name = job_name),
                          headers = headers)
        if r.status_code != 200:
            raise RuntimeError('Lease created with id {} at site {}, but failed to reload Jenkins page.'.format(lease_id, booking_site))
        
        print('Lease created with id {} at site {} and will start on {} (task will start 10 minutes later than lease start time.)'.format(lease_id, booking_site, start))
            
    else:
        raise RuntimeError('Reserve resource {node_type} on {site} failed!'.format(node_type=node_type, site=booking_site))
