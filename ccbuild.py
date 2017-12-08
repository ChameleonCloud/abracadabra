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

import whatsnew

PY3 = sys.version_info.major >= 3
if not PY3:
    raise RuntimeError('Python 2 not supported.')

BUILD_TAG = os.environ.get('BUILD_TAG', 'imgbuild-{}'.format(ulid.ulid()))
LATEST = 'latest'


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


def do_build(ip, repodir, commit, revision, metadata, *, variant='base'):
    if not revision.strip():
        raise ValueError('must provide revision to use')

    remote = RemoteControl(ip=ip)
    print('waiting for remote to start')
    remote.wait()
    print('remote contactable!')

    # init remote repo
    remote.run('rm -rf ~/build.git', quiet=True)
    out = remote.run('git init --bare build.git', quiet=True)
    print(out)

    # push to remote
    proc = run('git push --all ssh://cc@{ip}/~/build.git'.format(ip=ip), cwd=repodir, env={
        'GIT_SSH_COMMAND': 'ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no',
    })
    print(proc.stdout)
    print(proc.stderr)
    if proc.returncode != 0:
        raise RuntimeError()

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
        cmd = 'python create-image.py --revision {revision} {variant}'.format(
            revision=revision, variant=variant)
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
    parser.add_argument('--node-type', type=str, default='compute')
    parser.add_argument('--key-name', type=str, default='default',
        help='SSH keypair name on OS used to create an instance.')
    parser.add_argument('--builder-image', type=str, default='CC-CentOS7',
        help='Name or ID of image to launch.')
    parser.add_argument('--no-clean', action='store_true',
        help='Do not clean up on failure.')
    parser.add_argument('--automated', action='store_true',
        help='Skip interactive parts')
    parser.add_argument('--centos-revision', type=str,
        help='CentOS 7 revision to use. Defaults to latest.')
    parser.add_argument('--ubuntu-release', type=str,
        help='Build an Ubuntu image from provided release. Don\'t combine '
             'with --centos-revision', choices=['trusty', 'xenial'])
    # parser.add_argument('--force', action='store_true',
    #     help='Only build if the variant revision isn\'t already in Glance')
    parser.add_argument('--variant', type=str, default='base',
        help='Image variant to build.')
    parser.add_argument('build_repo', type=str,
        help='Path of repo to push and build.')

    args = parser.parse_args()
    session, rc = auth.session_from_args(args, rc=True)

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
                print('Requested revision "{}" not found. Available revisions: {}'.format(image_revision, available_revs), file=sys.stderr)
                return 1
    else:
        os_slug = 'ubuntu-{}'.format(args.ubuntu_release)
        number = {'trusty': '14.04', 'xenial': '16.04'}[args.ubuntu_release]
        repo_location = 'https://github.com/ChameleonCloud/CC-Ubuntu{}'.format(number)

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
    pprint(metadata)

    print('Lease: creating...')
    lease_name = 'lease-{}'.format(BUILD_TAG)
    server_name = 'instance-{}'.format(BUILD_TAG)
    with Lease(session, name=lease_name, node_type=args.node_type, _no_clean=args.no_clean) as lease:
        print(' - started {}'.format(lease))

        print('Server: creating...')
        server = lease.create_server(name=server_name, key=args.key_name, image=args.builder_image)
        print(' - building...')
        server.wait()
        print(' - started {}...'.format(server))
        server.associate_floating_ip()
        print(' - bound ip {} to server.'.format(server.ip))

        build_results = do_build(server.ip, args.build_repo, commit, image_revision, metadata, variant=args.variant)
        pprint(build_results)

        glance_results = do_upload(server.ip, rc, metadata, **build_results)
        pprint(glance_results)

        if args.automated:
            # done, skip the manual test stuff.
            return

        input('paused. continue to rebuild instance with new image. (server at {})'.format(server.ip))

        server.rebuild(glance_results['id'])
        server.wait()

        input('paused. continue to tear down instance and lease. (server at {})'.format(server.ip))

        print('Tearing down...')
    print('done.')


if __name__ == '__main__':
    sys.exit(main(sys.argv))
