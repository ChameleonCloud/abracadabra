#!/bin/bash
set -o errexit

NODE_TYPE=${NODE_TYPE:-gpu_p100} # overrideable in case the P100s are all taken

# my dev machine doesn't accept python3.6, but IUS only installed python3.6
# could symlink it on Jenkins, but this is maybe less disruptive.
if command -v python3 >/dev/null 2>&1
then
  PY3=python3
else
  PY3=python3.6
fi

$PY3 -m venv venv3
source venv3/bin/activate

set -o xtrace

python --version

pip --version
pip install --upgrade pip > pip.log
pip --version
pip install -r requirements.txt >> pip.log

pip freeze | grep hammers # hammers version (master branch, so somewhat volatile)

rm -rf CC-CentOS7
git clone https://github.com/ChameleonCloud/CC-CentOS7.git CC-CentOS7

# check the keypair exists
nova keypair-show default > /dev/null

python ccbuild.py \
  --centos-revision latest \
  --builder-image CC-CentOS7 \
  --node-type $NODE_TYPE \
  --variant gpu \
  --glance-info image_data.json \
  CC-CentOS7
