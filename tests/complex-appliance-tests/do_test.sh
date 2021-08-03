#! /bin/bash
set -o errexit
set -o nounset

COMPLEX_APPLIANCE_NAME=$1
KEY_NAME=$2

TARGET_FOLDER=venv

if command -v python3 >/dev/null 2>&1
then
  PY3=python3
else
  PY3=python3.6
fi

$PY3 -m venv $TARGET_FOLDER
set +o nounset
source ${TARGET_FOLDER}/bin/activate
set -o nounset

set -o xtrace

python --version
pip install --upgrade pip > pip.log
pip --version
pip install --requirement ../../requirements.txt >> pip.log

# add -s to disable all capturing; pytest doesn't allow stdin, but fabric uses stdin
if [ $# == 2 ]; then
	pytest -s "${COMPLEX_APPLIANCE_NAME}.py" --key-name=${KEY_NAME}
elif [ $# == 3 ]; then
	LEASE_ID=$3
	pytest -s "${COMPLEX_APPLIANCE_NAME}.py" --use-lease=${LEASE_ID} --key-name=${KEY_NAME}
	cd ..
	python cleanup_auto_created_lease.py --lease-id ${LEASE_ID}
fi