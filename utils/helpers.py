from fabric import connection as fconn
from keystoneauth1 import loading, session
import os
import shlex
import smtplib
import subprocess
import textwrap
from utils import whatsnew


def get_latest_revision(distro, release):
    newest = whatsnew.Newest()
    class_method = getattr(newest, distro)
    return class_method(release)["revision"]


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
    with fconn.Connection(
        ip,
        user="cc",
        connect_kwargs={
            "key_filename": os.environ.get('SSH_KEY_FILE', None),
        }
    ) as c:
        return c.run(warn=True, *args, **kwargs)


def get_local_rev(path):
    head = run('git rev-parse HEAD', cwd=str(path)).stdout.strip()
    return head


def send_notification_mail(relay, from_email, to_emails, image):
    # TODO: add detailed instructions
    help_url = "https://chameleoncloud.org/user/help/"
    message = f"""
    MIME-Version: 1.0
    Content-type: text/html
    Subject: New Chameleon image has been released

    <p>We have released a new version of {image["name"]}!</p>

    <p>Distro: {image["build-distro"]}</p>
    <p>Release: {image["build-release"]}</p>
    <p>Variant: {image["build-variant"]}</p>
    <p>Base Image Revision: {image["build-os-base-image-revision"]}</p>
    <p>Build Timestamp" {image["build-timestamp"]}</p>

    <p>
    Please use the Chemaleon image-pulling tool to download the latest version!
    </p>

    <p><i>This is an automatic email, please <b>DO NOT</b> reply!
    If you have any question or issue with the image, please submit
    a ticket on our <a href="{help_url}">help desk</a>.
    </i></p>

    <p>Thanks,</p>
    <p>Chameleon Team</p>
    """

    smtpObj = smtplib.SMTP(relay)
    smtpObj.sendmail(from_email, to_emails, message)

