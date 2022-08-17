#!/usr/bin/env python
from setuptools import setup, find_packages

setup(
    name='chameleon_image_tools',
    description='Chameleon Image Tools',
    packages=find_packages(),

    author='Chameleon',
    author_email='systems@list.chameleoncloud.org',
    url='https://github.com/ChameleonCloud/abracadabra',

    entry_points={
        'console_scripts': [
            'deploy = site_tools.deployer:main',
            'clean = site_tools.cleaner:main',
            'ipa_test = site_tools.ipa_tester:main',
        ],
    },

    classifiers=[
        'Programming Language :: Python :: 3',
        'Intended Audience :: System Administrators',
        'Topic :: Utilities',
    ],

)
