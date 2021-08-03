#!/bin/bash
set -o errexit

TASK=$1
PARAMS=$2

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
pip install -r ../requirements.txt >> pip.log

if [ $TASK == "auto-release" ]; then
	eval "python jenkins_appliance_update_check_and_build_trigger.py $PARAMS"
elif [ $TASK == "auto-test" ]; then
	eval "python jenkins_periodic_tests_setup.py $PARAMS"
else
	echo "Unknown task $TASK"
	exit 1
fi