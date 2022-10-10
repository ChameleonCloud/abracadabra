import errno
import os
import pytest
import socket
import sys
import time

sys.path.append("../..")

from keystoneauth1.exceptions.http import InternalServerError

from chi import lease as chi_lease
from chi import server as chi_server
import chi
import collections
import paramiko
import secrets
import spur
import traceback
from utils import helpers


BUILD_TAG = '{}-test'.format(os.environ.get('BUILD_TAG', secrets.token_hex(5)))
NODETYPE_DEFAULT = 'compute_haswell'
VARIANT_NODETYPE_DEFAULTS = {
    'base': 'compute_haswell',
    'gpu': 'gpu_p100',
    'fpga': 'fpga',
}


def pytest_addoption(parser):
    parser.addoption('--image', help='Image (name or ID) to use. Required.')
    parser.addoption('--variant',
                     help='Variant to test ("base", "gpu", "fpga", etc.) If not provided, '
                     'inferred from image metadata.',
                     )
    parser.addoption('--node-type',
                     help='Node type to launch on. If not provided, inferred from image '
                     'metadata.'
                     )
    parser.addoption('--distro',
                     help='Linux distro to test. If not provided, inferred from image '
                     'metadata.',
                     )
    parser.addoption('--release',
                     help='Release to test. If not provided, inferred from image '
                     'metadata.',
                     )
    parser.addoption('--rc', help='RC file with OpenStack credentials')
    parser.addoption(
        '--key-name', type=str, default=os.environ.get('SSH_KEY_NAME', 'default'),
        help='SSH keypair name on OS used to create an instance. Also looks at '
             'envvar SSH_KEY_NAME before using default "default".',
    )
    parser.addoption(
        '--key-file', type=str,
        default=os.environ.get('SSH_KEY_FILE', '~/.ssh/id_rsa'),
        help='Path to SSH key associated with the key-name. If not provided, '
             'falls back to envvar SSH_KEY_FILE then to "~/.ssh/id_rsa"',
    )
    parser.addoption(
        '--network-name', type=str,
        default='sharednet1',
        help='Name of network to launch instance on.',
    )
    parser.addoption(
        '--use-lease', type=str,
        help='Launch servers with this preexisting lease UUID.',
    )


@pytest.fixture(scope='session')
def keystone(request):
    try:
        session = helpers.get_auth_session_from_rc(helpers.get_rc_from_env())
    except Exception as e:
        pytest.exit('Failed to set up Keystone fixture: {}'.format(e))

    return session


@pytest.fixture(scope='session')
def image(request, keystone):
    image_arg = request.config.getoption('--image')
    if not image_arg:
        pytest.exit('--image argument is required.')

    glance = chi.glance(session=keystone)
    image = list(glance.images.list(filters={'name': image_arg}))
    if len(image) != 1:
        image = list(glance.images.list(filters={'id': image_arg}))
        if len(image) != 1:
            pytest.exit(
                'No single image found with name or ID: "{}"'.format(image_arg))

    image = image[0]
    image_id = image['id']
    image_distro = image.get('build-distro', request.config.getoption("--distro"))
    image_release = image.get('build-release', request.config.getoption("--release"))
    image_variant = image.get(
        'build-variant', request.config.getoption("--variant")
    )

    if image_distro is None or image_release is None or image_variant is None:
        pytest.exit('Image does not contain distro/release/variant in metadata. Cannot '
                    'automatically infer test parameter; they must be '
                    'manually specified.')

    return {
        'id': image_id,
        'distro': image_distro,
        'release': image_release,
        'variant': image_variant,
    }


@pytest.fixture(scope='session')
def server(request, keystone, image):
    ssh_key_name = request.config.getoption('--key-name')
    ssh_key_file = os.path.expanduser(request.config.getoption('--key-file'))
    node_type = request.config.getoption('--node-type')
    if not node_type:
        node_type = VARIANT_NODETYPE_DEFAULTS.get(
            image['variant'], NODETYPE_DEFAULT)

    server_name = 'instance-{}'.format(BUILD_TAG)
    existing_lease_id = request.config.getoption('--use-lease')
    if existing_lease_id:
        print('Lease: using existing with UUID {}'.format(existing_lease_id))
        lease = chi_lease.get_lease(existing_lease_id)
    else:
        print('Lease: creating...')
        lease_name = 'lease-{}'.format(BUILD_TAG)
        reservations = []
        chi_lease.add_node_reservation(reservations, count=1, node_type=node_type)
        lease = chi_lease.create_lease(lease_name, reservations)

    chi_lease.wait_for_active(lease['id'])
    print(' - started {}'.format(lease))
    
    reservation_id = chi_lease.get_node_reservation(lease['id'])
    server = chi_server.create_server(server_name,
                                      image_id=image['id'],
                                      flavor_name="baremetal",
                                      key_name=ssh_key_name,
                                      reservation_id=reservation_id)

    print(' - building...')
    chi_server.wait_for_active(server.id)

    print(' - started {}...'.format(server))
    ip = chi_server.associate_floating_ip(server.id)
    print(' - bound ip {} to server.'.format(ip))
    print('waiting for remote to start')
    chi_server.wait_for_tcp(ip, port=22)
    print('remote contactable!')
    
    server = server.__dict__
    server["floating_ip"] = ip

    yield server
    
    chi_server.delete_server(server["id"])


@pytest.fixture(scope='session')
def shell(request, server):
    ssh_key_file = os.path.expanduser(request.config.getoption('--key-file'))
    shell = spur.SshShell(
        hostname=server["floating_ip"],
        username='cc',
        missing_host_key=spur.ssh.MissingHostKey.warn,
        private_key_file=ssh_key_file,
        load_system_host_keys=False,
        connect_timeout=300,
    )
    with shell:
        yield shell


@pytest.fixture(autouse=True)
def skip_by_distro(request, image):
    if request.node.get_closest_marker('require_distro'):
        req_distro = request.node.get_closest_marker('require_distro').args[0]
        if not (image['distro'] == req_distro or image['distro'] in req_distro):
            pytest.skip('test only for distro "{}", image has "{}"'
                        .format(req_distro, image['distro']))

@pytest.fixture(autouse=True)
def skip_by_release(request, image):
    if request.node.get_closest_marker('require_release'):
        req_release = request.node.get_closest_marker('require_release').args[0]
        if not (image['release'] == req_release or image['release'] in req_release):
            pytest.skip('test only for release "{}", image has "{}"'
                        .format(req_release, image['release']))


@pytest.fixture(autouse=True)
def skip_by_variant(request, image):
    if request.node.get_closest_marker('require_variant'):
        req_variant = request.node.get_closest_marker(
            'require_variant').args[0]
        # print(req_variant)
        # print(image)
        # print(image['variant'] not in req_variant)
        if not (image['variant'] == req_variant or image['variant'] in req_variant):
            pytest.skip('test only for variant "{}", image has "{}"'
                        .format(req_variant, image['variant']))
    if request.node.get_closest_marker('skip_variant'):
        skip_variant = request.node.get_closest_marker('skip_variant').args[0]
        if image['variant'] == skip_variant or image['variant'] in skip_variant:
            pytest.skip(
                'test skipped for variant "{}"'.format(image['variant']))


@pytest.fixture(autouse=True)
def skip_by_region(request):
    if request.node.get_closest_marker('require_region'):
        req_region = request.node.get_closest_marker('require_region').args[0]
        if os.environ['OS_REGION_NAME'] != req_region:
            pytest.skip('test only for region "{}", but current region is "{}"'.format(
                req_region, os.environ['OS_REGION_NAME']))
