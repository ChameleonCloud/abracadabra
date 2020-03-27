import configparser
import io
import operator
import re
import sys
from html.parser import HTMLParser

import requests

PATHS = {7: 'https://cloud.centos.org/centos/7/images/',
         8: 'https://cloud.centos.org/centos/8/x86_64/images/'}

class TableParser(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self)
        self.in_td = False
        self.content_list = []
    
    def handle_starttag(self, tag, attrs):
        if tag == 'td':
            self.in_td = True
    
    def handle_data(self, data):
        if self.in_td:
            self.content_list.append(data.strip())
    
    def handle_endtag(self, tag):
        self.in_td = False

def newest_centos(release):
    p = TableParser()
    p.feed(requests.get(PATHS[release]).text)
    
    if release == 7:
        genericcloud_file_pattern = r'^CentOS-7-x86_64-GenericCloud-(\d[0-9_-]*).qcow2.xz$'
    if release == 8:
        genericcloud_file_pattern = r'^CentOS-8-GenericCloud-(\d[0-9.]*)-(.*).qcow2$'
    last_modified_pattern = r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2})$'
    image_date_dict = {}
    current_file = None
    
    for content in p.content_list:
        if re.match(genericcloud_file_pattern, content):
            image_date_dict[content] = None
            current_file = content
        elif re.match(last_modified_pattern, content) and current_file:
            image_date_dict[current_file] = content
        else:
            current_file = None  
            
    latest_file_name = max(image_date_dict.items(), key=operator.itemgetter(1))[0]
    
    m = re.search(genericcloud_file_pattern, latest_file_name)
    if m:
        return {'revision': m.group(1)}
            
    return None


def centos7():
    '''
    Returns the latest version of the CentOS 7 cloud image.
    '''
    return newest_centos(7)


# https://github.com/openstack/diskimage-builder/blob/master/diskimage_builder/elements/ubuntu/root.d/10-cache-ubuntu-tarball#L23
# automatically gets most recent **daily** cloud-image from https://cloud-images.ubuntu.com/xenial/current/
# but the most recent in the parent directory seems to be what it is.
UBUNTU_SERVER = 'https://cloud-images.ubuntu.com'

def newest_ubuntu(release):
    '''
    Given the release codeword, returns the latest version of the Ubuntu cloud image.

    14.04 - trusty
    16.04 - xenial
    17.04 - zesty
    17.10 - artful
    18.04 - bionic
    '''
    revision = 'unknown'
    response = requests.get('{}/{}/current/unpacked/build-info.txt'.format(UBUNTU_SERVER, release))
    response.raise_for_status()
    for line in response.text.splitlines():
        if line.startswith('serial='):
            revision = line.split('=', 1)[1].strip()

    return {'revision': revision}

def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    print(centos7())
    print(newest_ubuntu('xenial'))



if __name__ == '__main__':
    sys.exit(main(sys.argv))
