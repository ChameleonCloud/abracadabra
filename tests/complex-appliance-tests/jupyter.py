from __future__ import absolute_import, print_function

import datetime
import json
import os
import re
import requests
import subprocess
import time

from ccmanage import lease as ccmanagelease
from ccmanage import auth as ccmanageauth
from ccmanage import stack as ccmanagestack
from ccmanage import ssh as ccmanagessh

UUID_REGEX = '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
MAX_CONNECTION_ATTEMPTS = 90
SLEEP_SEC_BETWEEN_ATTEMPTS = 10 

def test_jupyterhub(keyname):
    session = ccmanageauth.session_from_args()
    
    lease_id = None
    floating_ip_id = None
    network_name = None
    reservation_id = None
    
    # create a lease using https://github.com/ChameleonCloud/heat-templates/blob/master/jupyter/reservation.sh
    outputs = subprocess.run('curl -L https://raw.githubusercontent.com/ChameleonCloud/heat-templates/master/jupyter/reservation.sh | bash', 
                             shell=True, 
                             stdout=subprocess.PIPE).stdout.decode('utf-8').split('\n')
        
    for output in outputs:
        m = re.search(fr'^\|\s*id\s*\|\s*({UUID_REGEX})\s*\|$', output)
        if m: lease_id = m.group(1)
        m = re.search(fr'^-\s*floating_ip=({UUID_REGEX})$', output)
        if m: floating_ip_id = m.group(1)
        m = re.search(r'^-\s*network_name=(.*)$', output)
        if m: network_name = m.group(1)
        m = re.search(fr'^-\s*reservation_id=({UUID_REGEX})$', output)
        if m: reservation_id = m.group(1)
            
    lease = ccmanagelease.Lease.from_existing(session, lease_id)
    lease._preexisting = False
        
    with lease:
        print('Lease ready, launching stack.')
        stack = ccmanagestack.Stack(url='https://www.chameleoncloud.org/appliances/api/appliances/72/template', 
                                    verbose=True,
                                    exit_delay=60,
                                    stack_name='appliance-test-jupyterhub',
                                    parameters={
                                        'reservation_id': reservation_id,
                                        'floating_ip': floating_ip_id,
                                        'network_name': network_name,
                                        'key_name': keyname
                                    })
        with stack:
            print('Stack ready.')
            # get floating ip address
            floating_ip = json.loads(subprocess.run(f'openstack floating ip show {floating_ip_id} -f json', 
                                                   shell=True, 
                                                   stdout=subprocess.PIPE).stdout.decode('utf-8'))['floating_ip_address']
            username = os.environ['OS_USERNAME']
            url = f'https://{floating_ip}'
            login_url = f'{url}/hub/login'
            lab_url = f'{url}/hub/user/{username}/lab'
            spawn_url = f'{url}/hub/spawn/{username}'
            login_payload = {'username': username,
                             'password': os.environ['OS_PASSWORD']}
            
            for attempt in range(MAX_CONNECTION_ATTEMPTS):
                try:
                    if requests.get(url, verify=False).status_code == 200:
                        break
                    else:
                        time.sleep(SLEEP_SEC_BETWEEN_ATTEMPTS)
                except Exception:
                    time.sleep(SLEEP_SEC_BETWEEN_ATTEMPTS)
            
            if requests.get(url, verify=False).status_code != 200:
                raise ConnectionError('Can not connect via floating ip')
            
            with requests.Session() as session:
                response = session.get(lab_url, verify=False)
                if not response.url.startswith(login_url):
                    raise ValueError('Can not redirect to log in page')

                response = session.post(response.url, data=login_payload, verify=False, allow_redirects=True)
                if  response.url != lab_url:
                    raise PermissionError('Can not login to jupyterhub')

                response = session.post(spawn_url, verify=False, allow_redirects=True)
                
                # check docker container exists
                remote = ccmanagessh.RemoteControl(ip=floating_ip)
                print('waiting for remote to start')
                remote.wait()
                print('remote contactable!')
                docker_output = remote.run('sudo docker container ls --format \'{{.ID}}\\t{{.Status}}\\t{{.Names}}\'')
                if f'jupyter-{username}' not in docker_output:
                    raise ValueError('container not started')

                
        print('Tearing down stack.')
    print('Success! Tearing down lease.')