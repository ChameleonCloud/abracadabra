#!/usr/bin/env python
'''
TODO: Not yet functional.

Distribute images to the various infrastructures.

Environment/RC file will be used to determine the source of the image. The
source image will be copied to the other two infrastructures with the
specified name (intent to be something like "rc-CC-...") and the source
image renamed to match.

This script does the copying on a remote system named "m01-07" because cURLing
from there is really fast. (You need to be able to "ssh m01-07" as per your
ssh config or it won't work)

After doing this:

1. (optional?) Sanity boot & connect test on each infrastructure
2. Rename all the three old images to something like "CC-...-[ version ]"
3. Rename the new images, removing the "rc-" or however.
4. Update the IDs on the portal catalog (https://www.chameleoncloud.org/appliances/)
'''


auth_urls = {
    'uc': '',
    'tacc': '',
    'kvm': '',
}


def main(argv=None):
    if argv is None:
        argv = sys.argv

    parser = argparse.ArgumentParser(description=__doc__)

    auth.add_arguments(parser)
    parser.add_argument('image', type=str,
        help='Name or ID of image to push around. Using ID highly suggested.')
    parser.add_argument('new_name' type=str,
        help='New name of the image')
    parser.add_argument('--public', action='store_true',
        help='Mark images as public')

    args = parser.parse_args(argv[1:])
    session, rc = auth.session_from_args(args, rc=True)

    # determine the site, make other RCs for the others...

    # copy the images

    # rename


if __name__ == '__main__':
    sys.exit(main(sys.argv))
