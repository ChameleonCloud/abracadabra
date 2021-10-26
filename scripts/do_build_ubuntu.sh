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

set +o nounset
source venv3/bin/activate
set -o nounset

set -o xtrace

python --version

pip --version
pip install --upgrade pip > pip.log
pip --version
pip install -r ../requirements.txt >> pip.log

IMAGEINFO_FILE_TAG=$(openssl rand -base64 12)
IMAGEINFO_FILE=$(pwd)/imageinfo.${IMAGEINFO_FILE_TAG}.json
LOCAL_REPO=CC-Ubuntu
REMOTE_REPO=https://github.com/ChameleonCloud/CC-Ubuntu.git
REMOTE_BRANCH=master

if ! [ -z ${BUILDER_BRANCH:+x} ]; then
        REMOTE_BRANCH=$BUILDER_BRANCH
fi

# clean up from other builds
rm -f build.log

if [ -d $LOCAL_REPO ]
then
  OLD_HEAD=$(git -C $LOCAL_REPO rev-parse HEAD)
  rm -rf $LOCAL_REPO
  git clone -b $REMOTE_BRANCH $REMOTE_REPO $LOCAL_REPO
  {
    echo '          Changes'
    echo '=============================='
  } 2> /dev/null # suppress trace https://superuser.com/a/1141026/18931
  git -C $LOCAL_REPO log ${OLD_HEAD}..

else
  git clone -b $REMOTE_BRANCH $REMOTE_REPO $LOCAL_REPO
fi

# check the keypair exists
nova keypair-show ${SSH_KEY_NAME:-default}

if [ $UBUNTU_RELEASE = 'focal' ]; then
  BUILDER_IMAGE=${BUILDER_IMAGE:-CC-Ubuntu20.04}
elif [ $UBUNTU_RELEASE = 'bionic' ]; then
  BUILDER_IMAGE=${BUILDER_IMAGE:-CC-Ubuntu18.04}
else
  echo "Unrecognized ubuntu release $UBUNTU_RELEASE"
  exit 1
fi

if [ $VARIANT = 'gpu' ]; then
  NODE_TYPE=${NODE_TYPE:-gpu_p100} # overrideable in case the P100s are all taken
  CUDA_VERSION=${CUDA_VERSION:-cuda11} #overrideable for other cuda versions
elif [ $VARIANT = 'arm64' ]; then
  NODE_TYPE=${NODE_TYPE:-compute_haswell}
fi

BUILD_ARGS="--ubuntu-release $UBUNTU_RELEASE "
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
if ! [ -z ${CUDA_VERSION:+x} ]; then
  BUILD_ARGS+="--cuda-version $CUDA_VERSION "
fi

date # to compare timestamps if there are failures
python ccbuild.py $BUILD_ARGS $LOCAL_REPO

if [ $VARIANT = 'arm64' ]; then
  # skip test for arm64 for now as we don't have resources at core sites
  exit 0
fi

# trying to avoid 'No valid host was found. There are not enough hosts available.' error
sleep 5m

cd ../tests/image-tests
date
TEST_BUILD_ARGS+="--image=$(jq -r .\"id\" $IMAGEINFO_FILE)"
pytest $TEST_BUILD_ARGS
rm -f ${IMAGEINFO_FILE}

cd ../../scripts
if ! [ -z ${EXISTING_LEASE:+x} ]; then
  python cleanup_auto_created_lease.py --lease-id $EXISTING_LEASE
fi
