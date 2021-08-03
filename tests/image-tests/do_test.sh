#! /bin/bash
set -o errexit
set -o nounset

NODE_TYPE=$1
IMAGE_NAME=$2

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

if [ $# == 2 ]; then
	pytest --image=${IMAGE_NAME} --node-type=${NODE_TYPE} --tb=short -s
elif [ $# == 3 ]; then
	LEASE_ID=$3
	pytest --image=${IMAGE_NAME} --node-type=${NODE_TYPE} --use-lease=${LEASE_ID} --tb=short -s
	cd ../../scripts
	python cleanup_auto_created_lease.py --lease-id ${LEASE_ID}
fi
