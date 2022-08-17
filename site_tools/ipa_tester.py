import argparse
import chi
from chi import lease as chi_lease
from chi import server as chi_server
import logging
from novaclient import exceptions as nova_exp
import operator
import random
import string
import sys
import time

from utils import helpers

logging.basicConfig(level=logging.INFO)
NAME = "CC-IPA-TEST-{node_type}-{tag}"


def _tag_generator(size=6, chars=string.ascii_uppercase + string.digits):
    return ''.join(random.choice(chars) for _ in range(size))


def _get_latest_image(query):
    glance = chi.glance()
    matching_images = list(glance.images.list(filters=query))
    matching_images.sort(
        reverse=True, key=operator.itemgetter('created_at'))
    latest_image = next(iter(matching_images), None)
    if not latest_image:
        raise ValueError(
            f"No latest image found with query {query}"
        )
    return latest_image["id"]


def _get_latest_ipa_image(ipa):
    query = {
        'status': 'active',
        'build-ipa': ipa,
    }
    return _get_latest_image(query)


def _get_latest_ubuntu_image():
    query = {
        'status': 'active',
        'build-distro': 'ubuntu',
        'build-variant': 'base',
    }
    return _get_latest_image(query)


def _reserve_resource(node_type, tag):
    reservations = []
    chi_lease.add_node_reservation(reservations, count=1, node_type=node_type)
    lease = chi_lease.create_lease(NAME.format(node_type=node_type, tag=tag),
                                   reservations)
    if not lease:
        raise RuntimeError("Failed to create lease! Try again later!")

    chi_lease.wait_for_active(lease['id'])
    reservation_id = chi_lease.get_node_reservation(lease["id"])

    for alloc in chi.blazar().host.list_allocations():
        for res in alloc["reservations"]:
            if res["lease_id"] == lease["id"]:
                host = chi.blazar().host.get(alloc["resource_id"])
                return lease["id"], reservation_id, host["hypervisor_hostname"]

    chi_lease.delete_lease(lease["id"])
    raise RuntimeError("Failed to find the eserved host!")


def _get_ipa_image(node_id):
    ironic = chi.ironic()
    node = ironic.node.get(node_id)
    kernel = None
    ramdisk = None
    if "deploy_kernel" in node.driver_info:
        kernel = node.driver_info["deploy_kernel"]
    if "deploy_ramdisk" in node.driver_info:
        ramdisk = node.driver_info["deploy_ramdisk"]

    return kernel, ramdisk


def _set_ipa_image(node_id, kernel_image_id, ramdisk_image_id):
    ironic = chi.ironic()
    patch = []
    if kernel_image_id:
        patch.append({
             "op": "add",
             "path": "/driver_info/deploy_kernel",
             "value": kernel_image_id
        })
    else:
        patch.append({
             "op": "remove",
             "path": "/driver_info/deploy_kernel",
        })

    if ramdisk_image_id:
        patch.append({
             "op": "add",
             "path": "/driver_info/deploy_ramdisk",
             "value": ramdisk_image_id
        })
    else:
        patch.append({
             "op": "remove",
             "path": "/driver_info/deploy_kernel",
        })

    ironic.node.update(node_id, patch)


def _create_instance(reservation_id, node_type, tag):
    server = chi_server.create_server(
        NAME.format(node_type=node_type, tag=tag),
        image_id=_get_latest_ubuntu_image(),
        flavor_name="baremetal",
        key_name="default",
        reservation_id=reservation_id
    )

    return server.id


def _wait_for_delete(server_id, timeout=(60 * 10), sleep_time=5):
    start_time = time.perf_counter()

    while True:
        try:
            chi_server.show_server(server_id)
        except nova_exp.NotFound:
            return
        time.sleep(sleep_time)
        if time.perf_counter() - start_time >= timeout:
            raise TimeoutError((
                f'Waited too long for deleting server {server_id}'))


def _get_all_nodes(node_type):
    result = []
    for host in chi.blazar().host.list():
        if "node_type" in host and host["node_type"] == node_type:
            result.append(host["hypervisor_hostname"])
    return result


def main(argv=None):
    if argv is None:
        argv = sys.argv

    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("--site-yaml", type=str, required=True,
                        help="A yaml file with site credentials.")
    parser.add_argument('--node-type', type=str, required=True,
                        help='Test IPA images on a specified node type')
    parser.add_argument('--initramfs-image', type=str,
                        help=('Specific initramfs image id to test;'
                              'default to latest'))
    parser.add_argument('--kernel-image', type=str,
                        help=('Specific kernel image id to test;'
                              'default to latest'))
    parser.add_argument('--push', action='store_true',
                        help=('update all nodes for the chosen node type '
                              'to use the tested ipa image'))

    args = parser.parse_args(argv[1:])

    chi.reset()
    helpers.set_chi_session_from_yaml(args.site_yaml)

    target_kernel_image = args.kernel_image
    if not target_kernel_image:
        target_kernel_image = _get_latest_ipa_image("kernel")
    target_ramdisk_image = args.initramfs_image
    if not target_ramdisk_image:
        target_ramdisk_image = _get_latest_ipa_image("initramfs")

    test_tag = _tag_generator()

    lease_id, reservation_id, host = _reserve_resource(
        args.node_type, test_tag
    )
    logging.info(f"Reserved node {host}")
    orig_kernel, orig_ramdisk = _get_ipa_image(host)
    _set_ipa_image(host, target_kernel_image, target_ramdisk_image)

    try:
        server_id = _create_instance(reservation_id, args.node_type, test_tag)
        chi_server.wait_for_active(server_id)
        logging.info(
            (f"Images {target_kernel_image} and {target_ramdisk_image} "
             "passed the test!")
        )
        chi_server.delete_server(server_id)
        _wait_for_delete(server_id)
        if args.push:
            # set all nodes using new kernel and ramdisk images
            for node in _get_all_nodes(args.node_type):
                try:
                    _set_ipa_image(
                        node, target_kernel_image, target_ramdisk_image
                    )
                except Exception:
                    logging.exception(
                        f"Failed to set kernel and ramdisk image for {node}"
                    )
        else:
            # reset the reserved node
            _set_ipa_image(host, orig_kernel, orig_ramdisk)
    except Exception:
        logging.exception(
            (f"Images {target_kernel_image} and {target_ramdisk_image} "
             "failed the test!")
        )
        try:
            chi_server.delete_server(server_id)
            _wait_for_delete(server_id)
            _set_ipa_image(host, orig_kernel, orig_ramdisk)
        except Exception:
            logging.exception("Failed to delete server or reset driver info")

    chi_lease.delete_lease(lease_id)


if __name__ == '__main__':
    sys.exit(main(sys.argv))
