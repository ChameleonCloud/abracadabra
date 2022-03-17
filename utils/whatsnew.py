from html.parser import HTMLParser
import operator
import re
import requests
import yaml


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


class Newest:
    def _get_releases(self, distro):
        with open("../supports.yaml", 'r') as f:
            supports = yaml.safe_load(f)

        releases = supports["supported_distros"][distro]["releases"]

        return releases

    def centos(self, release):
        support_centos = self._get_releases("centos")
        release_spec = support_centos[release]

        path = release_spec["base_image_path"]
        genericcloud_file_pattern = release_spec["genericcloud_file_pattern"]

        p = TableParser()
        p.feed(requests.get(path).text)

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

        latest_file_name = max(image_date_dict.items(),
                               key=operator.itemgetter(1))[0]

        m = re.search(genericcloud_file_pattern, latest_file_name)
        if m:
            return {'revision': m.group(1)}

        return None

    def ubuntu(self, release):
        support_ubuntu = self._get_releases("ubuntu")
        release_spec = support_ubuntu[release]

        path = release_spec["base_image_path"]
        revision = 'unknown'
        response = requests.get(
            '{}/{}/current/unpacked/build-info.txt'.format(path, release))
        response.raise_for_status()
        for line in response.text.splitlines():
            if line.startswith('serial='):
                revision = line.split('=', 1)[1].strip()

        return {'revision': revision}
