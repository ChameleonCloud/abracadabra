import os
import sys

sys.path.append("..")

import argparse
import base64
from chi import lease as chi_lease
from chi import server as chi_server
import chi
from fabric import api as fapi
from fabric import context_managers as fcm
import functools
import io
import json
from pprint import pprint
from swiftclient.client import Connection as swift_conn
import ulid
from utils import helpers
from utils import whatsnew


PY3 = sys.version_info.major >= 3
if not PY3:
    raise RuntimeError('Python 2 not supported.')

BUILD_TAG = os.environ.get('BUILD_TAG', 'imgbuild-{}'.format(ulid.ulid()))
LATEST = 'latest'
UBUNTU_VERSIONS = {
    'bionic': '18.04',
    'focal': '20.04',
}


def do_build(ip, repodir, commit, metadata, *,
             variant='base', cuda_version='cuda11', session):

    chi.server.wait_for_tcp(ip, port=22)
    print('remote contactable!')

    ssh_key_file = os.environ.get('SSH_KEY_FILE', None)
    region = os.environ['OS_REGION_NAME']

    ssh_args = ['-o UserKnownHostsFile=/dev/null',
                '-o StrictHostKeyChecking=no']

    # if fpga, download installation packages from Chameleon object storage
    if variant == 'fpga':
        tmp_fpga_dir = '/tmp/fpga'
        if region == 'CHI@TACC':
            objects = ['aocl-rte-16.0.0-1.x86_64.rpm', 'nalla_pcie_16.0.2.tgz']
        elif region == 'CHI@UC':
            objects = ['aocl-pro-rte-17.1.0-240.x86_64.rpm',
                       'QuartusProProgrammerSetup-17.1.0.240-linux.run',
                       'de5a_net_e1.tar.gz']
        else:
            raise RuntimeError('Region incorrect!')
        helpers.run('mkdir -p {}'.format(tmp_fpga_dir))
        helpers.remote_run(
            ip=ip, command='sudo mkdir -p {}'.format(tmp_fpga_dir))

        swift_connection = swift_conn(session=session,
                                      os_options={'region_name': region},
                                      preauthurl=session.get_endpoint(
                                          service_type='object-store',
                                          region_name=region,
                                          interface='public')
                                      )
        for obj in objects:
            print('downloading {}'.format(obj))
            resp_headers, obj_contents = swift_connection.get_object(
                'FPGA', obj)
            with open('{}/{}'.format(tmp_fpga_dir, obj), 'wb') as local:
                local.write(obj_contents)
            if ssh_key_file:
                proc = helpers.run('scp -i {} {} {}/{} cc@{}:'
                                   .format(ssh_key_file,
                                           ' '.join(
                                               ssh_args),
                                           tmp_fpga_dir,
                                           obj, ip))
            else:
                proc = helpers.run(
                    'scp {} {}/{} cc@{}:'.format(' '.join(ssh_args),
                                                 tmp_fpga_dir,
                                                 obj, ip))
            print(' - stdout:\n{}\n - stderr:\n{}\n--------'.format(
                proc.stdout, proc.stderr
            ))
            if proc.returncode != 0:
                raise RuntimeError('scp to remote failed!')
            else:
                helpers.remote_run(
                    ip=ip, command='sudo mv ~/{} {}/'.format(obj, tmp_fpga_dir))
                helpers.remote_run(
                    ip=ip, command='sudo chmod -R 755 {}'.format(tmp_fpga_dir))

        # clean up
        helpers.run('rm -rf {}'.format(tmp_fpga_dir))
        helpers.remote_run(ip=ip, command='sudo ls -la /tmp/fpga')

    # init remote repo
    helpers.remote_run(ip=ip, command='rm -rf ~/build.git', quiet=True)
    out = helpers.remote_run(
        ip=ip, command='git init --bare build.git', quiet=True)
    print(out)

    print('- pushing repo to remote')
    # GIT_SSH_COMMAND setup (requires Git 2.3.0+, CentOS repos have ~1.8)
    git_ssh_args = ssh_args

    if ssh_key_file:
        print('  - using ssh keyfile at: {}'.format(ssh_key_file))
        git_ssh_args.append('-i {}'.format(ssh_key_file))
    proc = helpers.run('git push --all ssh://cc@{ip}/~/build.git'
                       .format(ip=ip),
                       cwd=repodir,
                       env={
                           'GIT_SSH_COMMAND': 'ssh {}'
                           .format(' '.join(git_ssh_args)),
                       })
    print(' - stdout:\n{}\n - stderr:\n{}\n--------'.format(
        proc.stdout, proc.stderr
    ))
    if proc.returncode != 0:
        raise RuntimeError('repo push to remote failed')

    # checkout local rev on remote
    helpers.remote_run(ip=ip, command='rm -rf ~/build', quiet=True)
    helpers.remote_run(
        ip=ip, command='git clone ~/build.git ~/build', quiet=True)
    with fapi.cd('/home/cc/build'):
        helpers.remote_run(
            ip=ip,
            command='git -c advice.detachedHead=false checkout {head}'.format(
                head=commit)
        )
        helpers.remote_run(ip=ip, command='ls -a')

    out = io.StringIO()

    # install build reqs
    helpers.remote_run(ip=ip, command='sudo bash ~/build/install-reqs.sh',
                       pty=True, capture_buffer_size=10000, stdout=out)

    env = {
        # shell_env doesn't do escaping; quotes get mangled. base64 skips that.
        'DIB_CC_PROVENANCE': base64.b64encode(
            json.dumps(metadata).encode('ascii')
        ).decode('ascii'),
    }
    # there's a lot of output and it can do strange things if we don't
    # use a buffer or file or whatever
    with fapi.cd('/home/cc/build/'), fcm.shell_env(**env):
        # generate release option for trusty/xenial
        if metadata['build-os'].startswith('ubuntu'):
            ubuntu_release = metadata['build-os'].split('-')[1]
            release = '--release {}'.format(ubuntu_release)
        else:
            # centos
            centos_release = metadata['build-os'].replace('centos', '')
            release = '--release {}'.format(centos_release)

        if variant == 'gpu':
            cuda = '--cuda-version {}'.format(cuda_version)
        else:
            cuda = ''

        cmd = ('python create-image.py {release} '
               '--variant {variant} {cuda} --region {region}').format(
            release=release,
            variant=variant,
            cuda=cuda,
            region=region,
        )
        # DO THE THING
        helpers.remote_run(ip=ip, command=cmd, pty=True,
                           capture_buffer_size=10000, stdout=out)

    with open('build.log', 'w') as f:
        print(f.write(out.getvalue()))

    out.seek(0)
    ibi = '[{ip}] out: Image built in '.format(ip=ip)
    for line in out:
        if not line.startswith(ibi):
            continue
        output_file = line[len(ibi):].strip()
        break
    else:
        raise RuntimeError("didn't find output file in logs.")
    print(output_file)
    checksum = helpers.remote_run(ip=ip, command='md5sum {output_file}'.format(
        output_file=output_file)).split()[0].strip()

    return {
        'image_loc': output_file,
        'checksum': checksum,
    }


def do_upload(ip, rc, metadata, disk_format, **build_results):
    session = helpers.get_auth_session_from_rc(rc)
    glance = chi.glance(session=session)

    if disk_format != 'qcow2':
        converted_image = None
        if build_results['image_loc'].endswith('.qcow2'):
            converted_image = build_results['image_loc'][:-6] + '.img'
        else:
            converted_image = build_results['image_loc'] + '.img'
        out = helpers.remote_run(
            ip=ip,
            command='qemu-img convert -f qcow2 -O {} {} {}'.format(
                disk_format, build_results['image_loc'], converted_image)
        )
        if out.failed:
            raise RuntimeError('converting image failed')
        build_results['image_loc'] = converted_image
        build_results['checksum'] = helpers.remote_run(
            ip=ip,
            command='md5sum {}'.format(converted_image)).split()[0].strip()

    image = glance.images.create(
        name='image-{}-{}'.format(metadata['build-os'],
                                  metadata['build-tag']
                                  ),
        disk_format=disk_format,
        container_format='bare',
        **metadata
    )

    upload_command = helpers.image_upload_curl(session.get_token(),
                                               session.get_endpoint(service_type="image"),
                                               image['id'], build_results['image_loc'])
    out = helpers.remote_run(ip=ip, command=upload_command)

    image = glance.images.get(image["id"])

    if build_results['checksum'] != image['checksum']:
        raise RuntimeError('checksum mismatch! build: {} vs glance: {}'.format(
            repr(build_results['checksum']),
            repr(image['checksum']),
        ))

    return image


def main(argv=None):
    if argv is None:
        argv = sys.argv

    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument('--node-type', type=str, default='compute_haswell')
    parser.add_argument('--use-lease', type=str,
                        help='Use the already-running lease ID '
                        '(no lease creation or deletion). '
                        'Obviates --node-type and --no-clean.')
    parser.add_argument('--net-name', type=str, default='sharednet1',
                        help='Network name to launch the builder instance on.')
    parser.add_argument('--key-name', type=str,  # default='default',
                        help='SSH keypair name on OS used to create an '
                        'instance. The envvar SSH_KEY_NAME is also looked '
                        'at as a fallback, then it defaults to "default".')
    parser.add_argument('--builder-image', type=str, default='CC-CentOS8',
                        help='Name or ID of image to launch.')
    parser.add_argument('--no-clean', action='store_true',
                        help='Do not clean up on failure.')
    parser.add_argument('--centos-release', type=int, choices=[7, 8],
                        help='CentOS release. Defaults to 8.')
    parser.add_argument('--ubuntu-release', type=str,
                        help='Build an Ubuntu image from provided release.',
                        choices=UBUNTU_VERSIONS)
    parser.add_argument('--variant', type=str, default='base',
                        help='Image variant to build.')
    parser.add_argument('--cuda-version', type=str, default='cuda10',
                        help=('CUDA version to install. '
                              'Ignore if the variant is not gpu.'))
    parser.add_argument('--glance-info', type=str,
                        help='Dump a JSON to this path with the Glance '
                        'info in it')
    parser.add_argument('build_repo', type=str,
                        help='Path of repo to push and build.')
    parser.add_argument('--disk-format', type=str,
                        default='qcow2', help='Disk format of the image')

    args = parser.parse_args()

    rc = helpers.get_rc_from_env()
    session = helpers.get_auth_session_from_rc(rc)

    if not args.key_name:
        args.key_name = os.environ.get('SSH_KEY_NAME', 'default')

    if args.centos_release and args.ubuntu_release:
        print('Only specify Ubuntu or CentOS options.', file=sys.stderr)
        return 1
    elif args.ubuntu_release:
        build_centos = False
        image_revision = whatsnew.newest_ubuntu(
            args.ubuntu_release)['revision']
    else:
        build_centos = True
        image_revision = whatsnew.newest_centos(
            args.centos_release)['revision']

    if build_centos:
        if args.centos_release == 7:
            os_slug = 'centos7'
        elif args.centos_release == 8:
            os_slug = 'centos8'
        repo_location = 'https://github.com/ChameleonCloud/CC-CentOS'

        print('Latest CentOS {} cloud image revision: {}'.format(
            args.centos_release, image_revision))
    else:
        os_slug = 'ubuntu-{}'.format(args.ubuntu_release)
        number = UBUNTU_VERSIONS[args.ubuntu_release]
        # yes, for all versions.
        repo_location = 'https://github.com/ChameleonCloud/CC-Ubuntu'

        name = '{} ({})'.format(number, args.ubuntu_release.capitalize())
        print('Latest Ubuntu {} cloud image revision: {}'.format(
            name, image_revision))

    commit = helpers.get_local_rev(args.build_repo)
    metadata = {
        'build-variant': args.variant,
        'build-os': os_slug,
        'build-os-base-image-revision': image_revision,
        'build-repo': repo_location,
        'build-repo-commit': commit,
        'build-tag': BUILD_TAG,
    }
    if args.variant == 'gpu':
        metadata['build-cuda-version'] = args.cuda_version
    pprint(metadata)

    print('Lease: creating...')
    lease_name = 'lease-{}'.format(BUILD_TAG)
    server_name = 'instance-{}'.format(BUILD_TAG)

    if args.use_lease:
        lease = chi_lease.get_lease(args.use_lease)
    else:
        reservations = []
        chi_lease.add_node_reservation(reservations, count=1, node_type=args.node_type)
        lease = chi_lease.create_lease(lease_name, reservations)

    chi_lease.wait_for_active(lease['id'])
    print(' - started {}'.format(lease['name']))

    print('Server: creating...')
    reservation_id = chi_lease.get_node_reservation(lease['id'])
    server = chi_server.create_server(server_name,
                                      image_name=args.builder_image,
                                      flavor_name="baremetal",
                                      key_name=args.key_name,
                                      reservation_id=reservation_id)

    print(' - building...')
    chi_server.wait_for_active(server.id)
    print(' - started {}...'.format(server.name))
    ip = chi_server.associate_floating_ip(server.id)

    build_results = do_build(ip, args.build_repo, commit, metadata,
                             variant=args.variant,
                             cuda_version=args.cuda_version,
                             session=session)
    pprint(build_results)

    glance_results = do_upload(
            ip, rc, metadata, args.disk_format, **build_results)
    pprint(glance_results)

    if args.glance_info:
        with open(args.glance_info, 'w') as f:
            json.dump(glance_results, f)

    print('Tearing down...')
    chi_server.delete_server(server.id)
    #chi_lease.delete_lease(lease['id'])

    print('done.')


if __name__ == '__main__':
    sys.exit(main(sys.argv))
