'''
clean up auto release lease
'''
import argparse
import sys

from ccmanage import auth
from ccmanage.lease import Lease

AUTO_BUILD_LEASE_PREFIX = 'appliance-auto-release-'

def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)

    auth.add_arguments(parser)
    parser.add_argument('--lease-id', type=str, default='id of the lease tend to be deleted', required=True)
    
    args = parser.parse_args()
    session, rc = auth.session_from_args(args, rc=True)
    
    lease = Lease.from_existing(session, id=args.lease_id)
    
    # if lease is created by auto-build, delete lease when build success
    if lease.name.startswith(AUTO_BUILD_LEASE_PREFIX):
        print("This is an auto-build lease ({}), so deleting...".format(lease.id))
        lease.delete()
        print("Lease {} ({}) has been deleted!".format(lease.name, lease.id))
    
if __name__ == '__main__':
    sys.exit(main(sys.argv))
