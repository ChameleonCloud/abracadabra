#!/bin/bash
set -o errexit
set -o nounset

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

LOCAL_REPO=CC-Ubuntu16.04
REMOTE_REPO=https://github.com/ChameleonCloud/CC-Ubuntu16.04.git

if [ -d $LOCAL_REPO ]
then
  OLD_HEAD=$(git -C $LOCAL_REPO rev-parse HEAD)
  rm -rf $LOCAL_REPO
  git clone $REMOTE_REPO $LOCAL_REPO
  {
    echo '          Changes'
    echo '=============================='
  } 2> /dev/null # suppress trace https://superuser.com/a/1141026/18931
  git -C CC-Ubuntu16.04 log ${OLD_HEAD}..

else
  git clone $REMOTE_REPO $LOCAL_REPO
fi

# check the keypair exists
nova keypair-show default > /dev/null

BUILD_ARGS='--automated '
BUILD_ARGS+='--ubuntu-release trusty '

if ! [ -z ${EXISTING_LEASE:+x} ]; then
  BUILD_ARGS+='--use-lease $EXISTING_LEASE '
fi

python ccbuild.py $BUILD_ARGS $LOCAL_REPO
