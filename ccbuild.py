import argparse
import base64
import functools
import io
import json
import os
from pprint import pprint
import shlex
import subprocess
import sys

from fabric import api as fapi
from fabric import context_managers as fcm
import ulid

from ccmanage import auth
from ccmanage.lease import Lease
from ccmanage.ssh import RemoteControl
from ccmanage.util import random_base32
from hammers.osapi import Auth
from hammers.osrest import glance

from swiftclient.client import Connection as swift_conn

import whatsnew

PY3 = sys.version_info.major >= 3
if not PY3:
    raise RuntimeError('Python 2 not supported.')

BUILD_TAG = os.environ.get('BUILD_TAG', 'imgbuild-{}'.format(ulid.ulid()))
LATEST = 'latest'
UBUNTU_VERSIONS = {
    'trusty': '14.04',
    'xenial': '16.04',
    'bionic': '18.04',
}


def run(command, **kwargs):
    runargs = {
        'stdout': subprocess.PIPE,
        'stderr': subprocess.PIPE,
        'universal_newlines': True,
        'shell': False
    }
    runargs.update(kwargs)
    if not runargs['shell']:
        command = shlex.split(command)
    return subprocess.run(command, **runargs)


def get_local_rev(path):
    # proc = run('git status', cwd='CC-Ubuntu16.04')
    # print(proc.stdout)
    head = run('git rev-parse HEAD', cwd=str(path)).stdout.strip()
    return head


def do_build(ip, repodir, commit, revision, metadata, *, variant='base', cuda_version='cuda10', is_kvm=False, session):
    if not revision.strip():
        raise ValueError('must provide revision to use')

    remote = RemoteControl(ip=ip)
    print('waiting for remote to start')
    remote.wait()
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
            objects = ['aoc-env-de5anet.sh', 'AOCLProSetup-17.1.0.240-linux.run', 'de5a_net_e1.tar.gz']
        else:
            raise RuntimeError('Region incorrect!')
        run('mkdir -p {}'.format(tmp_fpga_dir))
        remote.run('sudo mkdir -p {}'.format(tmp_fpga_dir))
        
        swift_connection = swift_conn(session=session, os_options={'region_name': region}, preauthurl=session.get_endpoint(service_type='object-store', region_name=region, interface='public'))
        for obj in objects:
            print('downloading {}'.format(obj))
            resp_headers, obj_contents = swift_connection.get_object('FPGA', obj)
            with open('{}/{}'.format(tmp_fpga_dir, obj), 'wb') as local:
                local.write(obj_contents)
            if ssh_key_file:
                proc = run('scp -i {} {} {}/{} cc@{}:'.format(ssh_key_file, ' '.join(ssh_args), tmp_fpga_dir, obj, ip))
            else:
                proc = run('scp {} {}/{} cc@{}:'.format(' '.join(ssh_args), tmp_fpga_dir, obj, ip))
            print(' - stdout:\n{}\n - stderr:\n{}\n--------'.format(
                proc.stdout, proc.stderr
                ))
            if proc.returncode != 0:
                raise RuntimeError('scp to remote failed!')
            else:
                remote.run('sudo mv ~/{} {}/'.format(obj, tmp_fpga_dir))
                remote.run('sudo chmod -R 755 {}'.format(tmp_fpga_dir))
        
        # clean up
        run('rm -rf {}'.format(tmp_fpga_dir))
        remote.run('sudo ls -la /tmp/fpga')

    # init remote repo
    remote.run('rm -rf ~/build.git', quiet=True)
    out = remote.run('git init --bare build.git', quiet=True)
    print(out)

    print('- pushing repo to remote')
    # GIT_SSH_COMMAND setup (requires Git 2.3.0+, CentOS repos have ~1.8)
    git_ssh_args = ssh_args
    
    if ssh_key_file:
        print('  - using ssh keyfile at: {}'.format(ssh_key_file))
        git_ssh_args.append('-i {}'.format(ssh_key_file))
    proc = run('git push --all ssh://cc@{ip}/~/build.git'.format(ip=ip), cwd=repodir, env={
        'GIT_SSH_COMMAND': 'ssh {}'.format(' '.join(git_ssh_args)),
    })
    print(' - stdout:\n{}\n - stderr:\n{}\n--------'.format(
        proc.stdout, proc.stderr
    ))
    if proc.returncode != 0:
        raise RuntimeError('repo push to remote failed')

    # checkout local rev on remote
    remote.run('rm -rf ~/build', quiet=True)
    remote.run('git clone ~/build.git ~/build', quiet=True)
    with fapi.cd('/home/cc/build'):
        remote.run('git -c advice.detachedHead=false checkout {head}'.format(head=commit))
        remote.run('ls -a')

    out = io.StringIO()

    # install build reqs
    remote.run('sudo bash ~/build/install-reqs.sh', pty=True, capture_buffer_size=10000, stdout=out)

    env = {
        # shell_env doesn't do escaping; quotes get mangled. base64 skips that.
        'DIB_CC_PROVENANCE': base64.b64encode(json.dumps(metadata).encode('ascii')).decode('ascii'),
    }
    # there's a lot of output and it can do strange things if we don't
    # use a buffer or file or whatever
    with fapi.cd('/home/cc/build/'), fcm.shell_env(**env):
        # generate release option for trusty/xenial
        if metadata['build-os'].startswith('ubuntu'):
            ubuntu_release = metadata['build-os'].split('-')[1]
            release = '--release {}'.format(ubuntu_release)
        else:
            release = ''
            
        if variant == 'gpu':
            cuda = '--cuda-version {}'.format(cuda_version)
        else:
            cuda = ''
            
        kvm = ''
        if is_kvm: kvm = '--kvm'

        cmd = 'python create-image.py --revision {revision} {release} --variant {variant} {cuda} {kvm} --region {region}'.format(
            revision=revision,
            release=release,
            variant=variant,
            cuda=cuda,
            kvm=kvm,
            region=region,
        )
        # DO THE THING
        remote.run(cmd, pty=True, capture_buffer_size=10000, stdout=out)

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
    checksum = remote.run('md5sum {output_file}'.format(output_file=output_file)).split()[0].strip()

    return {
        'image_loc': output_file,
        'checksum': checksum,
    }


def do_upload(ip, rc, metadata, **build_results):
    remote = RemoteControl(ip=ip)

    ham_auth = Auth(rc)

    image = glance.image_create(
        ham_auth,
        'image-{}-{}'.format(metadata['build-os'], metadata['build-tag']),
        extra=metadata,
    )

    upload_command = glance.image_upload_curl(ham_auth, image['id'], build_results['image_loc'])
    out = remote.run(upload_command)
    image_data = glance.image(ham_auth, image['id'])

    if build_results['checksum'] != image_data['checksum']:
        raise RuntimeError('checksum mismatch! build: {} vs glance: {}'.format(
            repr(build_results['checksum']),
            repr(image_data['checksum']),
        ))

    return image_data


def main(argv=None):
    if argv is None:
        argv = sys.argv

    parser = argparse.ArgumentParser(description=__doc__)

    auth.add_arguments(parser)
    parser.add_argument('--node-type', type=str, default='compute_haswell')
    parser.add_argument('--use-lease', type=str,
        help='Use the already-running lease ID (no lease creation or deletion). '
             'Obviates --node-type and --no-clean.')
    parser.add_argument('--net-name', type=str, default='sharednet1',
        help='Network name to launch the builder instance on.')
    parser.add_argument('--key-name', type=str, #default='default',
        help='SSH keypair name on OS used to create an instance. The envvar '
             'SSH_KEY_NAME is also looked at as a fallback, then it defaults '
             'to "default".')
    parser.add_argument('--builder-image', type=str, default='CC-CentOS7',
        help='Name or ID of image to launch.')
    parser.add_argument('--no-clean', action='store_true',
        help='Do not clean up on failure.')
    parser.add_argument('--centos-revision', type=str,
        help='CentOS 7 revision to use. Defaults to latest.')
    parser.add_argument('--ubuntu-release', type=str,
        help='Build an Ubuntu image from provided release. Don\'t combine '
             'with --centos-revision', choices=UBUNTU_VERSIONS)
    # parser.add_argument('--force', action='store_true',
    #     help='Only build if the variant revision isn\'t already in Glance')
    parser.add_argument('--variant', type=str, default='base',
        help='Image variant to build.')
    parser.add_argument('--cuda-version', type=str, default='cuda10',
        help='CUDA version to install. Ignore if the variant is not gpu.')
    parser.add_argument('--glance-info', type=str,
        help='Dump a JSON to this path with the Glance info in it')
    # parser.add_argument('--run-tests', action='store_true',
    #     help='Run tests after creating image.')
    parser.add_argument('build_repo', type=str,
        help='Path of repo to push and build.')
    parser.add_argument('--kvm', action='store_true', help='Present if build image for KVM site') 

    args = parser.parse_args()
    session, rc = auth.session_from_args(args, rc=True)

    if not args.key_name:
        args.key_name = os.environ.get('SSH_KEY_NAME', 'default')

    if args.centos_revision and args.ubuntu_release:
        print('Only specify Ubuntu or CentOS options.', file=sys.stderr)
        return 1
    elif args.ubuntu_release:
        build_centos = False
        image_revision = whatsnew.newest_ubuntu(args.ubuntu_release)['revision']
    else:
        build_centos = True
        image_revision = args.centos_revision if args.centos_revision else LATEST

    if build_centos:
        os_slug = 'centos7'
        repo_location = 'https://github.com/ChameleonCloud/CC-CentOS7'

        if image_revision == LATEST:
            image_revision = whatsnew.newest_image()['revision']
            print('Latest CentOS 7 cloud image revision: {}'.format(image_revision))
        else:
            available_revs = sorted(i['revision'] for i in whatsnew.image_index().values())
            if args.centos_revision not in available_revs:
                print('WARNING: Requested revision "{}" not found in index. Available revisions: {}'.format(image_revision, available_revs), file=sys.stderr)
                # return 1
    else:
        os_slug = 'ubuntu-{}'.format(args.ubuntu_release)
        number = UBUNTU_VERSIONS[args.ubuntu_release]
        repo_location = 'https://github.com/ChameleonCloud/CC-Ubuntu16.04' # yes, for all versions.

        name = '{} ({})'.format(number, args.ubuntu_release.capitalize())
        print('Latest Ubuntu {} cloud image revision: {}'.format(name, image_revision))

    commit = get_local_rev(args.build_repo)
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
        lease = Lease.from_existing(session, id=args.use_lease)
    else:
        lease = Lease(session, name=lease_name, node_type=args.node_type, _no_clean=args.no_clean)

    with lease:
        print(' - started {}'.format(lease))

        print('Server: creating...')
        server = lease.create_server(name=server_name, key=args.key_name, image=args.builder_image, net_name=args.net_name)
        print(' - building...')
        server.wait()
        print(' - started {}...'.format(server))
        server.associate_floating_ip()
        print(' - bound ip {} to server.'.format(server.ip))

        build_results = do_build(server.ip, args.build_repo, commit, image_revision, metadata, variant=args.variant, cuda_version=args.cuda_version, is_kvm=args.kvm, session=session)
        pprint(build_results)

        glance_results = do_upload(server.ip, rc, metadata, **build_results)
        pprint(glance_results)

        if args.glance_info:
            with open(args.glance_info, 'w') as f:
                json.dump(glance_results, f)

        print('Tearing down...')
        
    print('done.')


if __name__ == '__main__':
    sys.exit(main(sys.argv))
