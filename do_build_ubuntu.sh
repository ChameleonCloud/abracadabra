#!/bin/bash
set -o errexit
set -o nounset

#############
# required arguments
UBUNTU_RELEASE=$1
VARIANT=$2

# optional exported variables
# * EXISTING_LEASE - uses the lease ID (doesn't create it's own lease)
# * NODE_TYPE
# * BUILDER_IMAGE - image to build on (GPU drivers want the same kernel version)

# examples
# $ ./do_build_ubuntu.sh trusty base
# $ ./do_build_ubuntu.sh xenial gpu
# $ NODE_TYPE=gpu_k80 ./do_build_ubuntu.sh xenial gpu # p100s are taken
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

if [ $VARIANT = 'gpu' ]; then
  NODE_TYPE=${NODE_TYPE:-gpu_p100} # overrideable in case the P100s are all taken
  if [ $UBUNTU_RELEASE = 'xenial' ]; then
    BUILDER_IMAGE=${BUILDER_IMAGE:-CC-Ubuntu16.04}
  elif [ $UBUNTU_RELEASE = 'trusty' ]; then
    BUILDER_IMAGE=${BUILDER_IMAGE:-CC-Ubuntu14.04} # no support for trusty/gpu
  fi
elif [ $VARIANT = 'fpga' ]; then
  NODE_TYPE=${NODE_TYPE:-fpga} # no support for ubuntu/fpga
fi

BUILD_ARGS='--automated '
BUILD_ARGS+="--ubuntu-release $UBUNTU_RELEASE "
BUILD_ARGS+="--variant $VARIANT "

if ! [ -z ${EXISTING_LEASE:+x} ]; then
  BUILD_ARGS+="--use-lease $EXISTING_LEASE "
fi
if ! [ -z ${NODE_TYPE:+x} ]; then
  BUILD_ARGS+="--node-type $NODE_TYPE "
fi
if ! [ -z ${BUILDER_IMAGE:+x} ]; then
  BUILD_ARGS+="--builder-image $BUILDER_IMAGE "
fi

python ccbuild.py $BUILD_ARGS $LOCAL_REPO
