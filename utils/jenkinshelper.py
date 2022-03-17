'''
helper functions for jenkins
'''
import jenkins

JENKINS_URL = "https://jenkins.chameleoncloud.org/"
APPLIANCE_BUILDER_JOB_NAME = "builder"


def connect_to_jenkins(username, password):
    server = jenkins.Jenkins(
        JENKINS_URL, username=username, password=password
    )
    return server


def build_image(server, distro, release, variant):
    params = {
        "distro": distro,
        "release": release,
        "variant": variant
    }
    server.build_job(
        APPLIANCE_BUILDER_JOB_NAME, params
    )
