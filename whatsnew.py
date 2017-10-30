import configparser
import io
import operator
import sys

import requests

PATH = 'https://cloud.centos.org/centos/7/images/'
INDEX = PATH + 'image-index'
SUMS = PATH + 'sha256sum.txt'


def centos_sums():
    response = requests.get(SUMS)
    response.raise_for_status()
    sums = response.text
    sums = {
        filename.strip(): checksum.strip()
        for checksum, filename
        in (
            line.split(' ', 1)
            for line
            in sums.splitlines()
        )
    }
    return sums


def centos_images():
    response = requests.get(INDEX)
    response.raise_for_status()
    index = io.StringIO(response.text)
    cp = configparser.ConfigParser()
    cp.readfp(index)
    data = {sec: dict(cp.items(sec)) for sec in cp.sections()}
    return data


def image_index():
    data = centos_images()
    sums = centos_sums()

    for sec in data:
        data[sec]['url'] = PATH + data[sec]['file']
        data[sec]['sha256_xz'] = sums[data[sec]['file']]
    return data


def newest_image():
    return max(image_index().values(), key=operator.itemgetter('revision'))


def centos7():
    '''
    Returns the latest version of the CentOS 7 cloud image.
    '''
    return newest_image()


# https://github.com/openstack/diskimage-builder/blob/master/diskimage_builder/elements/ubuntu/root.d/10-cache-ubuntu-tarball#L23
# automatically gets most recent **daily** cloud-image from https://cloud-images.ubuntu.com/xenial/current/
# but the most recent in the parent directory seems to be what it is.
UBUNTU_SERVER = 'https://cloud-images.ubuntu.com/'
PATH_UBUNTU14 = UBUNTU_SERVER + 'trusty/'
PATH_UBUNTU16 = UBUNTU_SERVER + 'xenial/'

def newest_ubuntu(release):
    '''
    Returns the latest version of the Ubuntu 16.04 cloud image.
    '''
    assert release in {'trusty', 'xenial'}
    revision = 'unknown'
    response = requests.get('{}{}/current/unpacked/build-info.txt'.format(UBUNTU_SERVER, release))
    for line in response.text.splitlines():
        if line.startswith('serial='):
            revision = line.split('=', 1)[1].strip()

    return {'revision': revision}


def cuda8():
    ...


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    print(centos7())
    print(newest_ubuntu1604())



if __name__ == '__main__':
    sys.exit(main(sys.argv))
