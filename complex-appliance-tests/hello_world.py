from __future__ import absolute_import, print_function

import datetime
import os

from ccmanage import lease as ccmanagelease
from ccmanage import auth as ccmanageauth
from ccmanage import stack as ccmanagestack

def test_hello_world(uselease, keyname):
    session = ccmanageauth.session_from_args()
    
    if not uselease:
        # create a lease
        lease = ccmanagelease.Lease(session, name='appliance-test-hello-world', length=datetime.timedelta(minutes=60), node_type='compute_haswell', nodes=2)
    else:
        # use existing lease
        lease = ccmanagelease.Lease.from_existing(session, uselease)
        
    with lease:
        print('Lease ready, launching stack.')
        stack = ccmanagestack.Stack(url='https://www.chameleoncloud.org/appliances/api/appliances/26/template', 
                                    verbose=True,
                                    exit_delay=60,
                                    stack_name='appliance-test-hello-world',
                                    parameters={
                                        'reservation_id': lease.reservation,
                                        'key_name': keyname
                                    })
        with stack:
            print('Stack ready.')
                
        print('Tearing down stack.')
    print('Success! Tearing down lease.')