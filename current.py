import argparse
import sys

from hammers import osapi
from hammers.osrest import glance

import whatsnew


def need_update(auth):
    images = glance.images(auth, {'build-os': 'centos7'})

    try:
        appliance = max(images, key=lambda i: i.get('build-os-revision', ''))
    except ValueError:
        appliance = {}
        appliance_rev = ''
    else:
        appliance_rev = appliance['build-os-revision']

    latest_centos = whatsnew.centos7()

    available_rev = latest_centos['revision']

    print('latest appliance image rev: {} (id: {})'.format(appliance_rev, appliance.get('id')))
    print('latest available image rev: {}'.format(available_rev))

    return available_rev > appliance_rev


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(description=__doc__)

    osapi.add_arguments(parser)

    args = parser.parse_args()

    auth = osapi.Auth.from_env_or_args(args=args)

    if not need_update(auth):
        print('appliance up to date!')
        return

    print('-- need to rebuild appliance --')
    


if __name__ == '__main__':
    sys.exit(main(sys.argv))
