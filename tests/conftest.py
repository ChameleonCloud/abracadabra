import collections
import os
import secrets
import time
import traceback

from ccmanage import auth
from ccmanage.lease import Lease
from glanceclient import Client as GlanceClient
from keystoneauth1.exceptions.http import InternalServerError
import pytest
import spur

from util import single

BUILD_TAG = '{}-test'.format(os.environ.get('BUILD_TAG', secrets.token_hex(5)))
VARIANT_NODETYPE_DEFAULTS = {
    'base': 'compute',
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
    parser.addoption('--os',
        help='Operating system to test. If not provided, inferred from image '
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
    args = request.config.getoption('--rc')
    if args:
        # sham object with osrc attribute that session_from_args expects
        args = collections.namedtuple('ArgsRc', ['osrc'])(args)

    try:
        session = auth.session_from_args(args)
    except Exception as e:
        pytest.exit('Failed to set up Keystone fixture: {}'.format(e))

    return session


@pytest.fixture(scope='session')
def image(request, keystone):
    image_arg = request.config.getoption('--image')
    if not image_arg:
        pytest.exit('--image argument is required.')

    glance = GlanceClient('2', session=keystone)
    try:
        image = single(glance.images.list(filters={'name': image_arg}))
    except ValueError:
        try:
            image = single(glance.images.list(filters={'id': image_arg}))
        except ValueError:
            pytest.exit('No single image found with name or ID: "{}"'.format(image_arg))

    image_id = image['id']
    image_os = image.get('build-os', request.config.getoption("--os"))
    image_variant = image.get('build-variant', request.config.getoption("--variant"))

    if image_os is None or image_variant is None:
        pytest.exit('Image does not contain os/variant in metadata. Cannot '
                    'automatically infer test parameter; they must be '
                    'manually specified.')

    return {
        'id': image_id,
        'os': image_os,
        'variant': image_variant,
    }


@pytest.fixture(scope='session')
def server(request, keystone, image):
    ssh_key_name = request.config.getoption('--key-name')
    ssh_key_file = os.path.expanduser(request.config.getoption('--key-file'))
    net_name = request.config.getoption('--network-name')
    node_type = request.config.getoption('--node-type')
    if not node_type:
        node_type = VARIANT_NODETYPE_DEFAULTS.get(image['variant'], 'compute')

    server_name = 'instance-{}'.format(BUILD_TAG)
    existing_lease_id = request.config.getoption('--use-lease')
    if existing_lease_id:
        print('Lease: using existing with UUID {}'.format(existing_lease_id))
        lease = Lease.from_existing(keystone, existing_lease_id)
    else:
        print('Lease: creating...')
        lease_name = 'lease-{}'.format(BUILD_TAG)
        lease = Lease(
            keystone,
            name=lease_name,
            node_type=node_type,
            #_no_clean=args.no_clean,
        )

    try:
        with lease:
            print(' - started {}'.format(lease))

            try:
                print('Server: creating...')
                server = lease.create_server(name=server_name, key=ssh_key_name,
                                            net_name=net_name, image=image['id'])
                print(' - building...')
                server.wait()
                print(' - started {}...'.format(server))
                server.associate_floating_ip()
                print(' - bound ip {} to server.'.format(server.ip))
                print('waiting for remote to start')
                wait(server.ip, username='cc', private_key_file=ssh_key_file)
                print('remote contactable!')
            except Exception as e:
                # fatal problem, abort trying to do anything
                pytest.exit('Problem starting server: {}'.format(e))

            yield server

    except InternalServerError as exc:
        content = exc.response.content.decode('utf-8')
        if 'Not enough hosts' in content:
            pytest.exit('Unable to test, no hosts free.')
        pytest.fail('Problem starting lease/server: {}'.format(content))


@pytest.fixture
def shell(request, server):
    ssh_key_file = os.path.expanduser(request.config.getoption('--key-file'))
    shell = spur.SshShell(
        hostname=server.ip,
        username='cc',
        missing_host_key=spur.ssh.MissingHostKey.accept,
        private_key_file=ssh_key_file,
    )
    with shell:
        yield shell


def wait(host, username='cc', **shell_kwargs):
    shell_kwargs.setdefault('missing_host_key', spur.ssh.MissingHostKey.accept)
    print(f'wait({host!r}, username={username!r}, **{shell_kwargs!r})')

    error_counts = collections.defaultdict(int)
    for attempt in range(30):
        try:
            shell = spur.SshShell(
                hostname=host,
                username=username,
                **shell_kwargs,
            )
            with shell:
                # time.sleep(0.25)
                result = shell.run(['echo', 'hello'])
        except spur.ssh.ConnectionError as e:
            # example errors:
            # 'Error creating SSH connection\nOriginal error: Authentication failed.'
            # 'Error creating SSH connection\nOriginal error: [Errno 60] Operation timed out'
            # 'Error creating SSH connection\nOriginal error: [Errno None] Unable to connect to port 22 on [ip addr]'
            error_counts['spur.ssh.ConnectionError'] += 1
            pass

        # except paramiko.AuthenticationException as e:
            # while the ssh service starting, it can accept connections but auth isn't fully set.
            # error_counts['paramiko.AuthenticationException'] += 1
            # pass
        # except paramiko.ssh_exception.NoValidConnectionsError as e:
            # server might be down while starting
            # error_counts['paramiko.ssh_exception.NoValidConnectionsError'] += 1
            # pass
        except paramiko.SSHException as e:
            error_counts['paramiko.SSHException'] += 1
            # this also subsumes the other paramiko errors (above)

            # paramiko.ssh_exception.SSHException: Error reading SSH protocol banner
            # local interruptions?

            # error_counts['paramiko.SSHException'] += 1
            pass

        except socket.timeout as e:
            # if the floating IP is still kinda floating and not getting routed.
            error_counts['socket.timeout'] += 1
            pass

        except OSError as e:
            # filter so only capturing errno.ENETUNREACH
            if e.errno != errno.ENETUNREACH:
                raise
            error_counts['ENETUNREACH'] += 1
        else:
            print('contacted!')
            break

        print('.', end='')
        time.sleep(7.5)
    else:
        raise RuntimeError('failed to connect to {}@{}\n{}'.format(username, host, error_counts))


@pytest.fixture(autouse=True)
def skip_by_os(request, image):
    if request.node.get_marker('require_os'):
        req_os = request.node.get_marker('require_os').args[0]
        # print(req_os)
        # print(image)
        # print(not (image['os'] == req_os or image['os'] in req_os))
        if not (image['os'] == req_os or image['os'] in req_os):
            pytest.skip('test only for OS "{}", image has "{}"'
                        .format(req_os, image['os']))


@pytest.fixture(autouse=True)
def skip_by_variant(request, image):
    if request.node.get_marker('require_variant'):
        req_variant = request.node.get_marker('require_variant').args[0]
        # print(req_variant)
        # print(image)
        # print(image['variant'] not in req_variant)
        if not (image['variant'] == req_variant or image['variant'] in req_variant):
            pytest.skip('test only for variant "{}", image has "{}"'
                        .format(req_variant, image['variant']))
