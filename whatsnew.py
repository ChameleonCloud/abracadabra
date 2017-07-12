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


def cuda8():
    ...


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    centos7()


if __name__ == '__main__':
    sys.exit(main(sys.argv))
