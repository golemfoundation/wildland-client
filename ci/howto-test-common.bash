set -eo pipefail

. /home/user/env/bin/activate
pip install --no-deps . plugins/*

export PATH=$PATH:$(dirname "$0")/..
alias tree='/usr/bin/tree -A'
export LC_CTYPE=C.UTF-8

test_script=${BASH_SOURCE[-1]}
all_steps=$(grep -c '^run ' "$test_script")
current_step=0

. ci/howto-test-lib.bash
