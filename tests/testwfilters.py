import argparse
import os
import re
import sys

# from fabric import api as fapi
# from fabric import context_managers as fcm
import pytest


# def require_variant(variant):
#     def _req_var(test_func):
#         def interior(image, *args, **kwargs):
#             if image['variant'] != variant:
#                 pytest.skip('test not for variant')
#             test_func(*args, **kwargs)
#         return interior
#     return _req_var


@pytest.fixture
def thing():
    return 'thing'


# @require_variant('gpu')
# @pytest.mark.skipif('image["variant"] != "gpu"')
# @pytest.mark.require_os(['ubuntu-xenial', 'centos7'])
@pytest.mark.require_os('centos7')
# @pytest.mark.require_variant(['base', 'gpu'])
# @pytest.mark.require_variant('gpu')
@pytest.mark.require_variant('base')
def test_gpu_thing(image, thing):
    assert thing == 'thing'
    assert 1 == 0


# wrapper = require_variant('gpu')

# test_gpu_thing = wrapper(test_gpu_thing)
