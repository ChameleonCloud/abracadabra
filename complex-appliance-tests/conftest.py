import os
import pytest

def pytest_addoption(parser):
    parser.addoption(
        "--use-lease", type=str, help='Launch stacks with this preexisting lease UUID.'
    )
    parser.addoption(
        '--key-name', type=str, default=os.environ.get('SSH_KEY_NAME', 'default'),
        help='SSH keypair name on OS used to create an instance. Also looks at '
             'envvar SSH_KEY_NAME before using default "default".',
    )

@pytest.fixture
def uselease(request):
    return request.config.getoption("--use-lease")

@pytest.fixture
def keyname(request):
    return request.config.getoption("--key-name")