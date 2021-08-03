import os

from keystoneauth1 import loading, session

from fabric import api as fapi
import shlex
import subprocess
import textwrap

fapi.env.abort_on_prompts = True
fapi.env.disable_known_hosts = True
fapi.env.use_ssh_config = True
fapi.env.warn_only = True

fapi.env.key_filename = os.environ.get('SSH_KEY_FILE', None)


def get_auth_session_from_rc(rc):
    """
    Generates a Keystone Session from an OS parameter dictionary.  Dict
    key format is the same as environment variables (``OS_AUTH_URL``, et al.)
    """
    rc_opt_keymap = {key[3:].lower().replace(
        '_', '-'): key for key in rc if key.startswith('OS_')}
    loader = loading.get_plugin_loader('password')
    credentials = {}
    for opt in loader.get_options():
        if opt.name not in rc_opt_keymap:
            continue
        credentials[opt.name.replace('-', '_')] = rc[rc_opt_keymap[opt.name]]
    auth = loader.load_from_options(**credentials)
    return session.Session(auth=auth)


def get_rc_from_env():
    return {k: os.environ[k]
            for k in os.environ if k.startswith('OS_')}


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


def remote_run(ip, *args, **kwargs):
    with fapi.settings(user='cc', host_string=ip):
        return fapi.run(*args, **kwargs)


def get_local_rev(path):
    head = run('git rev-parse HEAD', cwd=str(path)).stdout.strip()
    return head


def image_upload_curl(auth_token, glance_endpoint, id, filepath):
    """Generates an cURL command to upload an image file at `filepath` to be
    associated with the Glance image. Includes authentication header, so
    is stateless and can be run most anywhere."""
    return textwrap.dedent('''\
    curl -i -X PUT -H "X-Auth-Token: {token}" \
        -H "Content-Type: application/octet-stream" \
        -H "Connection: keep-alive" \
        -T "{filepath}" \
        {url}'''.format(
        token=auth_token,
        filepath=filepath,
        url=glance_endpoint + '/v2/images/{}/file'.format(id),
    ))


def image_download_curl(auth_token, glance_endpoint, id, filepath):
    """Generates a cURL command to download an image file to `filepath`.
    If `filepath` is not provided, dumps to ``~/<image name>.img``. The
    request is authenticated, so can be run most anywhere."""
    return textwrap.dedent('''\
    curl -D /dev/stdout -X GET -H "X-Auth-Token: {token}" \
        -H "Connection: keep-alive" \
        {url} \
        -o {filepath}'''.format(
        token=auth_token,
        url=glance_endpoint + '/v2/images/{}/file'.format(id),
        filepath=filepath,
    ))
