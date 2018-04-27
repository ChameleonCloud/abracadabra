import argparse
import os
import re
import sys

from fabric import api as fapi
from fabric import context_managers as fcm
import ulid

from ccmanage import auth
from ccmanage.lease import Lease
from ccmanage.ssh import RemoteControl


BUILD_TAG = os.environ.get('BUILD_TAG', 'imgtest-{}'.format(ulid.ulid()))


def server_prep(test_func, session, args):
    print('Lease: creating...')
    lease_name = 'lease-{}'.format(BUILD_TAG)
    server_name = 'instance-{}'.format(BUILD_TAG)
    
    if args.use_lease:
        lease = Lease.from_existing(session, id=args.use_lease)
    else:
        lease = Lease(session, name=lease_name, node_type=args.node_type, _no_clean=args.no_clean)
        
    with lease:
        print(' - started {}'.format(lease))

        print('Server: creating...')
        server = lease.create_server(name=server_name, key=args.key_name, image=args.image)
        print(' - building...')
        server.wait()
        print(' - started {}...'.format(server))
        server.associate_floating_ip()
        print(' - bound ip {} to server.'.format(server.ip))

        remote = RemoteControl(ip=server.ip)
        print('waiting for remote to start')
        remote.wait()
        print('remote contactable!')

        print('starting tests...')
        test_func(remote)


def tests(remote):
    # check that the UID was set correctly
    out = remote.run('cat /etc/passwd')
    print(out.return_code)

    for line in out.splitlines():
        if line.startswith('ccadmin:'):
            assert re.match(r'^ccadmin:[^:]*:1010:', line)
        if line.startswith('cc:'):
            assert re.match(r'^cc:[^:]*:1000:', line)

    # check that the cc-tools are available
    out = remote.run('which cc-snapshot')
    print(out.return_code)

    out = remote.run('which cc-checks')
    print(out.return_code)

    out = remote.run('which etrace2')
    print(out.return_code)
    out = remote.run('etrace2 sleep 1')


def main(argv=None):
    if argv is None:
        argv = sys.argv

    parser = argparse.ArgumentParser(description=__doc__)

    auth.add_arguments(parser)
    parser.add_argument('--node-type', type=str, default='compute_haswell')
    parser.add_argument('--use-lease', type=str,
        help='Use the already-running lease ID (no lease creation or deletion). '
             'Obviates --node-type and --no-clean.')
    parser.add_argument('--key-name', type=str, default='default',
        help='SSH keypair name on OS used to create an instance.')
    parser.add_argument('--image', type=str, default='CC-Ubuntu16.04',
        help='Name or ID of image to launch.')
    parser.add_argument('--no-clean', action='store_true',
        help='Do not clean up on failure.')
    # parser.add_argument('--automated', action='store_true',
    #     help='Skip interactive parts')
    parser.add_argument('--variant', type=str, default='base',
        help='Image variant to test.')

    args = parser.parse_args(argv[1:])
    session, rc = auth.session_from_args(args, rc=True)

    server_prep(tests, session, args)


if __name__ == '__main__':
    sys.exit(main(sys.argv))
