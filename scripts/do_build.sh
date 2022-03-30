#!/bin/bash
set -o errexit
set -o nounset

#############
# required arguments
DISTRO=$1
RELEASE=$2
VARIANT=$3

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

REMOTE_BRANCH=master

if ! [ -z ${BUILDER_BRANCH:+x} ]; then
        REMOTE_BRANCH=$BUILDER_BRANCH
fi

# read yaml
SUPPORTED_DISTROS=$(python -c "import yaml,json;s=yaml.safe_load(open('../supports.yaml','r'));print(json.dumps(s['supported_distros']))")
DISTRO_SPEC=$(echo $SUPPORTED_DISTROS | jq -r .$DISTRO)
LOCAL_REPO=$(echo $DISTRO_SPEC | jq -r .local_repo)
REMOTE_REPO=$(echo $DISTRO_SPEC | jq -r .repo_location)
REMOTE_REPO=$REMOTE_REPO.git

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


RELEASES=$(echo $DISTRO_SPEC | jq -r .releases)
RELEASE_SPEC=$(echo $RELEASES | jq -r .[\"$RELEASE\"])
DEFAULT_BUILDER_IMAGE=$(echo $RELEASE_SPEC | jq -r .prod_name)
BUILDER_IMAGE=${BUILDER_IMAGE:-$DEFAULT_BUILDER_IMAGE}

SUPPORTED_VARIANTS=$(python -c "import yaml,json;s=yaml.safe_load(open('../supports.yaml','r'));print(json.dumps(s['supported_variants']))")
VARIANT_SPEC=$(echo $SUPPORTED_VARIANTS | jq -r .$VARIANT)
DEFAULT_NODE_TYPE=$(echo $VARIANT_SPEC | jq -r .builder_default_node_type)
NODE_TYPE=${NODE_TYPE:-$DEFAULT_NODE_TYPE}


BUILD_ARGS="--distro $DISTRO "
BUILD_ARGS+="--release $RELEASE "
BUILD_ARGS+="--variant $VARIANT "

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
new_image_id=$(python ccbuild.py $BUILD_ARGS $LOCAL_REPO | tail -1)

if ! [[ $new_image_id =~ ^\{?[A-F0-9a-f]{8}-[A-F0-9a-f]{4}-[A-F0-9a-f]{4}-[A-F0-9a-f]{4}-[A-F0-9a-f]{12}\}?$ ]]; then
    exit 0
fi

if [ $VARIANT = 'arm64' ]; then
  # skip test for arm64 for now as we don't have resources at core sites
  exit 0
fi

# trying to avoid 'No valid host was found. There are not enough hosts available.' error
sleep 5m

cd ../tests/image-tests
date
TEST_BUILD_ARGS+="--image=$new_image_id"
pytest $TEST_BUILD_ARGS