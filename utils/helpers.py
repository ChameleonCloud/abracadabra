import chi
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from fabric import connection as fconn
from jinja2 import Environment
from keystoneauth1.identity import v3
from keystoneauth1 import loading, session
import os
import shlex
import smtplib
import subprocess
from swiftclient.client import Connection as swift_conn
from utils import whatsnew
import yaml


CENTRALIZED_CONTAINER_NAME = "chameleon-images"
CENRTALIZED_CONTAINER_ACCOUNT = "AUTH_570aad8999f7499db99eae22fe9b29bb"
CENTRALIZED_CONTAINER_URL = \
    f"https://chi.tacc.chameleoncloud.org:7480/swift/v1/{CENRTALIZED_CONTAINER_ACCOUNT}/{CENTRALIZED_CONTAINER_NAME}"
CHAMELEON_CORE_SITES = ["uc", "tacc"]
CENTRALIZED_STORE = "swift"
CENTRALIZED_STORE_SITE = "tacc"
CENTRALIZED_STORE_REGION_NAME = "CHI@TACC"
SWIFT_META_HEADER_PREFIX = "x-object-meta-"


EMAIL_TEMPLATE = '''
<style type="text/css">
@font-face {
  font-family: 'Open Sans';
  font-style: normal;
  font-weight: 300;
  unicode-range: U+0460-052F, U+20B4, U+2DE0-2DFF, U+A640-A69F;
}
.body {
    width: 90%;
    margin: auto;
    font-family: 'Open Sans', 'Helvetica', sans-serif; 
    font-size: 11pt;
    color: #000000;
}
a:link { color: #B40057; text-decoration: underline}
a:visited { color: #542A95; text-decoration: none}
a:hover { color: #B40057; background-color:#C4FFF9; text-decoration: underline }
</style>

<div class="body">
<p>
We have released a new version of {{ image["name"] }} (id: {{ image["id"] }})!

<ul>
    <li>Distro: {{ image["build-distro"] }}</li>
    <li>Release: {{ image["build-release"] }}</li>
    <li>Variant: {{ image["build-variant"] }}</li>
    <li>Base image revision: {{ image["build-os-base-image-revision"] }}</li>
    <li>Build timestamp: {{ image["build-timestamp"] }}</li>
</ul>
</p>

<p>
If you have the automatic image deployer set via CHI-in-a-Box,
it will auto-deploy this image.
Otherwise, to download and deploy the latest version to your site:
</p>

<p><small>
<ul>
    <li>
    <code>
    docker pull docker.chameleoncloud.org/chameleon_image_tools:latest
    </code>
    </li>

    <li>
    <code>
    docker run --rm --net=host -v "/etc/chameleon_image_tools/site.yaml:/etc/chameleon_image_tools/site.yaml"
    docker.chameleoncloud.org/chameleon_image_tools:latest deploy
    --site-yaml /etc/chameleon_image_tools/site.yaml
    --image {{ image["id"] }}
    </code>
    </li>
</ul>
</small></p>

<p><i>This is an automatic email, please <b>DO NOT</b> reply!
If you have any question or issue with the image, please submit
a ticket on our <a href="https://chameleoncloud.org/user/help/">help desk</a>.
</i></p>

<p>Thanks,</p>
<p>Chameleon Team</p>

</div>
<br><br>
'''


def archival_name(prod_image_name, image):
    return "{}-{}-{}".format(
        prod_image_name,
        image["build-os-base-image-revision"],
        image["build-timestamp"]
    )


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


def get_auth_session_from_yaml(yaml_file):
    with open(yaml_file, 'r') as f:
        site = yaml.safe_load(f)
    admin_auth = v3.Password(
        auth_url=site["auth_url"],
        username=site["admin_username"],
        password=site["admin_password"],
        project_name=site["admin_project"],
        user_domain_id='default',
        project_domain_id='default'
    )
    return session.Session(auth=admin_auth)


def set_chi_session_from_yaml(yaml_file):
    with open(yaml_file, 'r') as f:
        site = yaml.safe_load(f)
    chi.set("auth_url", site["auth_url"])
    chi.set("username", site["admin_username"])
    chi.set("password", site["admin_password"])
    chi.set("project_name", site["admin_project"])
    chi.set("user_domain_id", 'default')
    chi.set("project_domain_id", 'default')
    chi.set("auth_type", "v3password")
    chi.set("region_name", site["region_name"])


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
    # renders a Jinja template into HTML
    templ = Environment().from_string(EMAIL_TEMPLATE)
    html = templ.render(image=image)

    msg = MIMEMultipart('alternative')
    msg['From'] = from_email
    msg['Subject'] = "New Chameleon image has been released"
    msg['To'] = ','.join(to_emails)
    msg.attach(MIMEText(html, 'html'))

    # send email
    server = smtplib.SMTP(relay, timeout=30)
    server.sendmail(from_email, to_emails, msg.as_string())
    server.quit()


def connect_to_swift_with_admin(session, region_name):
    swift_connection = swift_conn(session=session,
                                  os_options={'region_name': region_name},
                                  preauthurl=session.get_endpoint(
                                      service_type='object-store',
                                      region_name=region_name,
                                      interface='public'
                                      )
                                  )
    return swift_connection
