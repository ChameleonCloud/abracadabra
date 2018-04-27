#!/bin/bash
set -o errexit
set -o nounset

#############
# required arguments
VARIANT=$1

# optional exported variables
# * EXISTING_LEASE - uses the lease ID (doesn't create it's own lease)
# * NODE_TYPE
# * BUILDER_IMAGE - image to build on (GPU drivers want the same kernel version)

# examples
# $ ./do_build_centos.sh base
# $ ./do_build_centos.sh fpga
# $ NODE_TYPE=gpu_k80 ./do_build_centos.sh gpu # p100s are taken
#############

# my dev machine doesn't accept python3.6, but IUS only installed python3.6
# could symlink it on Jenkins, but this is maybe less disruptive.
if command -v python3 >/dev/null 2>&1
then
  PY3=python3
else
  PY3=python3.6
fi

$PY3 -m venv venv3

set +o nounset
source venv3/bin/activate
set -o nounset

set -o xtrace

python --version

pip --version
pip install --upgrade pip > pip.log
pip --version
pip install -r requirements.txt >> pip.log

pip freeze | grep hammers # hammers version (master branch, so somewhat volatile)

IMAGEINFO_FILE=$(pwd)/imageinfo.json
LOCAL_REPO=CC-CentOS7
REMOTE_REPO=https://github.com/ChameleonCloud/CC-CentOS7.git

# clean up from other builds
rm -f build.log $IMAGEINFO_FILE

if [ -d $LOCAL_REPO ]
then
  OLD_HEAD=$(git -C $LOCAL_REPO rev-parse HEAD)
  rm -rf $LOCAL_REPO
  git clone $REMOTE_REPO $LOCAL_REPO
  {
    echo '          Changes'
    echo '=============================='
  } 2> /dev/null # suppress trace https://superuser.com/a/1141026/18931
  git -C $LOCAL_REPO log ${OLD_HEAD}..

else
  git clone $REMOTE_REPO $LOCAL_REPO
fi

# check the keypair exists
nova keypair-show ${SSH_KEY_NAME:-default}

BUILDER_IMAGE=${BUILDER_IMAGE:-CC-CentOS7}
if [ $VARIANT = 'gpu' ]; then
  NODE_TYPE=${NODE_TYPE:-gpu_p100} # overrideable in case the P100s are all taken
elif [ $VARIANT = 'fpga' ]; then
  NODE_TYPE=${NODE_TYPE:-fpga}
fi

BUILD_ARGS="--centos-revision latest "
BUILD_ARGS+="--variant $VARIANT "
BUILD_ARGS+="--glance-info $IMAGEINFO_FILE "

TEST_BUILD_ARGS="--tb=short "

if ! [ -z ${EXISTING_LEASE:+x} ]; then
  BUILD_ARGS+="--use-lease $EXISTING_LEASE "
  TEST_BUILD_ARGS+="--use-lease $EXISTING_LEASE "
fi
if ! [ -z ${NODE_TYPE:+x} ]; then
  BUILD_ARGS+="--node-type $NODE_TYPE "
  TEST_BUILD_ARGS+="--node-type $NODE_TYPE "
fi
if ! [ -z ${BUILDER_IMAGE:+x} ]; then
  BUILD_ARGS+="--builder-image $BUILDER_IMAGE "
fi

date # to compare timestamps if there are failures
python ccbuild.py $BUILD_ARGS $LOCAL_REPO

cd tests
date
TEST_BUILD_ARGS+="--image=$(jq -r .\"id\" $IMAGEINFO_FILE)"
pytest $TEST_BUILD_ARGS
