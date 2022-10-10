import argparse
import base64
from chi import lease as chi_lease
from chi import server as chi_server
import chi
import datetime
import io
import json
import os
from pprint import pprint
from pyaml_env import parse_config
import sys
import textwrap
import ulid
from variant_extra_build_steps import ExtraSteps

sys.path.append("..")
from utils import helpers


PY3 = sys.version_info.major >= 3
if not PY3:
    raise RuntimeError('Python 2 not supported.')

BUILD_TAG = os.environ.get('BUILD_TAG', 'imgbuild-{}'.format(ulid.ulid()))


def do_build(ip, rc, repodir, commit, metadata, variant, extra_params):

    chi.server.wait_for_tcp(ip, port=22)
    print('remote contactable!')

    ssh_key_file = os.environ.get('SSH_KEY_FILE', None)

    ssh_args = ['-o UserKnownHostsFile=/dev/null',
                '-o StrictHostKeyChecking=no']

    extra_steps = getattr(ExtraSteps(), variant, None)
    if extra_steps:
        kwargs = {
            "region": os.environ['OS_REGION_NAME'],
            "ip": ip,
            "rc": rc,
            "ssh_key_file": ssh_key_file,
            "ssh_args": ssh_args,
        }
        extra_steps(**kwargs)

    # init remote repo
    helpers.remote_run(ip=ip, command='rm -rf ~/build.git')
    out = helpers.remote_run(
        ip=ip, command='git init --bare build.git')
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
    helpers.remote_run(ip=ip, command='rm -rf ~/build')
    helpers.remote_run(
        ip=ip, command='git clone ~/build.git ~/build')
    helpers.remote_run(
        ip=ip,
        command='cd /home/cc/build && git -c advice.detachedHead=false checkout {head}'.format(
            head=commit)
    )
    helpers.remote_run(ip=ip, command='ls -a')

    out = io.StringIO()

    # install build reqs
    helpers.remote_run(ip=ip, command='sudo bash ~/build/install-reqs.sh',
                       pty=True, out_stream=out)

    # there's a lot of output and it can do strange things if we don't
    # use a buffer or file or whatever
    cmd = ('export DIB_CC_PROVENANCE={provenance}; '
           'cd /home/cc/build/ && '
           'python3 create-image.py --release {release} '
           '--variant {variant} {extra_params}').format(
        provenance=base64.b64encode(
            json.dumps(metadata).encode('ascii')
        ).decode('ascii'),
        release=metadata["build-release"],
        variant=variant,
        extra_params=extra_params,
    )
    # DO THE THING
    helpers.remote_run(ip=ip, command=cmd, pty=True,
                       out_stream=out)

    with open('build.log', 'w') as f:
        print(f.write(out.getvalue()))

    out.seek(0)
    ibi = 'Image built in '
    for line in out:
        if not line.startswith(ibi):
            continue
        output_file = line[len(ibi):].strip()
        break
    else:
        raise RuntimeError("didn't find output file in logs.")

    out = io.StringIO()
    tmp_dir_file_name = output_file.rsplit('/', 1)
    tmp_dir = tmp_dir_file_name[0]
    file_name = tmp_dir_file_name[1]
    helpers.remote_run(
        ip=ip,
        command=f"find {tmp_dir} -type f -name '[{file_name}]*'",
        pty=True,
        out_stream=out
    )

    out.seek(0)
    result = []
    for img_file in out:
        img_file = img_file.strip()
        if metadata["build-distro"].startswith("ipa_"):
            ipa_image = img_file.rsplit('.', 1)[1]
            metadata["build-ipa"] = ipa_image
        checksum_result = helpers.remote_run(
            ip=ip, command=f"md5sum {img_file}"
        )
        checksum = checksum_result.stdout.split()[0].strip()
        result.append({
            'image_loc': img_file,
            'checksum': checksum,
            'metadata': metadata,
        })

    return result


def do_upload(ip, rc, disk_format, **build_results):
    session = helpers.get_auth_session_from_rc(rc)
    glance = chi.glance(session=session)
    metadata = build_results['metadata']

    if disk_format == 'raw':
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
        name='image-{}-{}-{}'.format(metadata['build-distro'],
                                     metadata['build-release'],
                                     metadata['build-tag'],
                                     ),
        disk_format=disk_format,
        container_format='bare',
        **metadata
    )

    upload_command = textwrap.dedent('''\
        curl -i -X PUT -H "X-Auth-Token: {token}" \
            -H "Content-Type: application/octet-stream" \
            -H "Connection: keep-alive" \
            -T "{filepath}" \
            {url}'''.format(
            token=session.get_token(),
            filepath=build_results['image_loc'],
            url=session.get_endpoint(service_type="image") + f"/v2/images/{image['id']}/file",
        ))
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

    supports = parse_config("../supports.yaml")

    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "--node-type",
        type=str,
        help="Create a lease for the builder with the selected node type"
    )
    parser.add_argument(
        "--use-lease",
        type=str,
        help="Use the already-running lease ID "
             "(no lease creation or deletion)."
             "Obviates --node-type and --no-clean."
    )
    parser.add_argument(
        "--key-name",
        type=str,
        help="SSH keypair name on OS used to create an "
             "instance. The envvar SSH_KEY_NAME is also looked "
             "at as a fallback, then it defaults to \"default\"."
    )
    parser.add_argument(
        "--builder-image",
        type=str,
        required=True,
        help='Name or ID of image to launch.'
    )
    parser.add_argument(
        "--distro",
        type=str,
        choices=supports["supported_distros"].keys(),
        required=True,
        help='Build the selected distro image'
    )
    parser.add_argument(
        "--release",
        type=str,
        required=True,
        help='Build the image from provided release.'
    )
    parser.add_argument(
        "--variant",
        type=str,
        choices=supports["supported_variants"].keys(),
        help="Image variant to build."
    )
    parser.add_argument(
        "--disk-format",
        type=str,
        default='qcow2',
        help='Disk format of the image'
    )
    parser.add_argument(
        "build_repo",
        type=str,
        help='Path of repo to push and build.'
    )

    args = parser.parse_args()

    rc = helpers.get_rc_from_env()

    if not args.key_name:
        args.key_name = os.environ.get('SSH_KEY_NAME', 'default')

    image_revision = helpers.get_latest_revision(args.distro, args.release)
    repo_location = supports["supported_distros"][args.distro]["repo_location"]

    print(f"Latest {args.distro}-{args.release} cloud image revision: {image_revision}")

    commit = helpers.get_local_rev(args.build_repo)
    metadata = {
        'build-variant': args.variant,
        'build-distro': args.distro,
        'build-release': args.release,
        'build-os-base-image-revision': image_revision,
        'build-repo': repo_location,
        'build-repo-commit': commit,
        'build-timestamp': str(datetime.datetime.now().timestamp()),
        'build-tag': BUILD_TAG,
        'build-ipa': "na",
    }
    if "variant_metadata" in supports["supported_variants"][args.variant]:
        metadata.update(supports["supported_variants"][args.variant]["variant_metadata"])
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
        if not lease:
            print("Not enough nodes to satisfy your request! Try again later!")
            return

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

    extra_params = supports["supported_distros"][args.distro].get(
        "extra_params", ""
    )

    build_results = do_build(ip, rc, args.build_repo, commit, metadata,
                             variant=args.variant,
                             extra_params=extra_params)
    pprint(build_results)

    for result in build_results:
        glance_results = do_upload(
                ip, rc, args.disk_format, **result
        )
        pprint(glance_results)

    print('Tearing down...')
    chi_server.delete_server(server.id)
    #chi_lease.delete_lease(lease['id'])

    print(glance_results["id"])


if __name__ == '__main__':
    sys.exit(main(sys.argv))
