from __future__ import absolute_import, print_function

import datetime
import os
import sys

import chi
from heatclient.client import Client as heatclient

sys.path.append("..")

from utils import helpers


def test_hello_world(uselease, keyname):
    rc = helpers.get_rc_from_env()
    session = helpers.get_auth_session_from_rc(rc)

    if not uselease:
        # create a lease
        lease = chi.lease.Lease(session, name='appliance-test-hello-world',
                                length=datetime.timedelta(minutes=60), node_type='compute_haswell', nodes=2)
    else:
        # use existing lease
        lease = chi.lease.Lease.from_existing(session, uselease)

    with lease:
        print('Lease ready, launching stack.')
        hc = heatclient(session=session)
        stack = hc.Sstacks.create(
            template='https://www.chameleoncloud.org/appliances/api/appliances/26/template',
            verbose=True,
            exit_delay=60,
            stack_name='appliance-test-hello-world',
            parameters={
                'reservation_id': lease.reservations[0]['id'],
                'key_name': keyname
            })
        with stack:
            print('Stack ready.')

        print('Tearing down stack.')
    print('Success! Tearing down lease.')
