'''
clean up auto release lease
'''
import sys

sys.path.append("..")

import argparse
from chi import lease as chi_lease
import chi
from utils import helpers


AUTO_BUILD_LEASE_PREFIX = 'appliance-auto-release-'
AUTO_TEST_LEASE_PREFIX = 'appliance-test-'


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument('--lease-id', type=str,
                        default='id of the lease tend to be deleted',
                        required=True)

    args = parser.parse_args()

    lease = chi_lease.get_lease(args.lease_id)

    # if lease is created by auto-build, delete lease when build success
    if lease["name"].startswith(AUTO_BUILD_LEASE_PREFIX):
        print("This is an auto-build lease ({}), so deleting..."
              .format(lease.id))
        lease.delete_lease(lease["id"])
        print("Lease {} ({}) has been deleted!".format(lease.name, lease.id))

    # if lease is created by auto-test, delete lease after testing
    if lease["name"].startswith(AUTO_TEST_LEASE_PREFIX):
        print("This is an auto-created lease ({}) for testing, so deleting..."
              .format(lease.id))
        lease.delete_lease(lease["id"])
        print("Lease {} ({}) has been deleted!".format(lease.name, lease.id))


if __name__ == '__main__':
    sys.exit(main(sys.argv))
