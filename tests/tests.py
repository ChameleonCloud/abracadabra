import argparse
import os
import re
import sys

# from fabric import api as fapi
# from fabric import context_managers as fcm
import pytest

# from ccmanage import auth
# from ccmanage.lease import Lease
# from ccmanage.ssh import RemoteControl

# @pytest.fixture(scope='session')
# def asdf(image):
#     print('init asdf')
#     yield
#     print('teardown asdf')

@pytest.mark.require_variant('gpu')
def test_cuda_driver_running(server, shell):
    # result = shell.run(['which', 'nvidia-smi'], encoding='utf-8')
    result = shell.run(['nvidia-smi'], encoding='utf-8')


def test_cc_snapshot_exists(server, shell):
    result = shell.run(['which', 'cc-snapshot'], encoding='utf-8')
    assert result.return_code == 0


def test_cc_snapshot_auth_fast_fail(server, shell):
    result = shell.run(['cc-snapshot'],
        encoding='utf-8',
        allow_error=True,
        update_env={
            'OS_USERNAME': 'not-a-real-user',
            'OS_PASSWORD': 'not-a-password-if-it-is-thats-crazy',
        },
    )
    assert result.return_code == 1
    assert 'check username' in result.output


@pytest.mark.require_os(['centos7', 'ubuntu-xenial']) # trusty cloud-init is too old
def test_uids(server, shell):
    result = shell.run(['id', '-u', 'cc'], encoding='utf-8')
    assert int(result.output.strip()) == 1000

    result = shell.run(['id', '-u', 'ccadmin'], encoding='utf-8')
    assert int(result.output.strip()) == 1010


@pytest.mark.require_os(['centos7', 'ubuntu-xenial']) # trusty doesn't have RAPL
def test_etrace2(server, shell):
    result = shell.run(['etrace2', 'sleep', '1'], encoding='utf-8')
    assert 'ETRACE2' in result.output

# @pytest.fixture(scope='session')
# def server(keystone, image):
#     pass
# def server_prep(test_func, session, args):
#     print('Lease: creating...')
#     lease_name = 'lease-{}'.format(BUILD_TAG)
#     server_name = 'instance-{}'.format(BUILD_TAG)
#     with Lease(session, name=lease_name, node_type=args.node_type, _no_clean=args.no_clean) as lease:
#         print(' - started {}'.format(lease))

#         print('Server: creating...')
#         server = lease.create_server(name=server_name, key=args.key_name, image=args.image)
#         print(' - building...')
#         server.wait()
#         print(' - started {}...'.format(server))
#         server.associate_floating_ip()
#         print(' - bound ip {} to server.'.format(server.ip))

#         remote = RemoteControl(ip=server.ip)
#         print('waiting for remote to start')
#         remote.wait()
#         print('remote contactable!')

#         print('starting tests...')
#         test_func(remote)


# def tests(remote):
#     # check that the UID was set correctly
#     out = remote.run('cat /etc/passwd')
#     print(out.return_code)

#     for line in out.splitlines():
#         if line.startswith('ccadmin:'):
#             assert re.match(r'^ccadmin:[^:]*:1010:', line)
#         if line.startswith('cc:'):
#             assert re.match(r'^cc:[^:]*:1000:', line)

#     # check that the cc-tools are available
#     out = remote.run('which cc-snapshot')
#     print(out.return_code)

#     out = remote.run('which cc-checks')
#     print(out.return_code)

#     out = remote.run('which etrace2')
#     print(out.return_code)
#     out = remote.run('etrace2 sleep 1')


def main(argv=None):
    if argv is None:
        argv = sys.argv

    parser = argparse.ArgumentParser(description=__doc__)

    auth.add_arguments(parser)
    parser.add_argument('--node-type', type=str, default='compute')
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
