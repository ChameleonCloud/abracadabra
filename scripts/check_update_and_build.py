'''
Compare the latest released Chameleon appliance with the latest base image.
Notify if Chameleon appliance needs update.
'''
import argparse
import chi
import json
import os
import shlex
import subprocess
import sys
import tempfile
import yaml
from . import imagedist

sys.path.append("..")
from utils import helpers, jenkinshelper


def get_image_by_name(auth_data, name):
    glance = chi.glance(
                session=helpers.get_auth_session_from_rc(auth_data)
            )
    images = list(glance.images.list(filters={
            'name': name, 'visibility': 'public'}))

    if len(images) > 1:
        raise ValueError(f"More than one {name} images found!")
    elif len(images) == 0:
        # first time deployment
        return None
    else:
        return images[0]


def main(argv=None):
    if argv is None:
        argv = sys.argv

    with open("../supports.yaml", 'r') as f:
        supports = yaml.safe_load(f)

    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument('auth_json', type=str,
                        help=("File with auth info in JSON format "
                              "for all sites."))
    parser.add_argument("--jenkins-yaml", type=str,
                        required=True,
                        help=("Jenkins yaml file including credentials"))

    args = parser.parse_args(argv[1:])

    with open(args.auth_json) as f:
        auth_data = json.load(f)["auths"]["tacc"]

    for distro in supports["supported_distros"].keys():
        releases = supports["supported_distros"][distro]
        for release in releases:
            # get latest base image revision
            latest_base_image_revision = helpers.get_latest_revision(distro, release)
            variant = release["variants"]
            image_production_name = imagedist.production_name(
                distro=distro, release=release, variant=variant)
            current_image = get_image_by_name(auth_data, image_production_name)
            if (
                not current_image or
                    current_image["build-os-base-image-revision"] != latest_base_image_revision
            ):
                # release new image
                with open(args.jenkins.yaml, 'r') as f:
                    jenkins_creds = yaml.safe_load(f)
                jenkins_server = jenkinshelper.connect_to_jenkins(
                    jenkins_creds["username"], jenkins_creds["passwords"]
                )
                jenkinshelper.build_image(
                    jenkins_server, distro, release, variant
                )


if __name__ == '__main__':
    sys.exit(main(sys.argv))
