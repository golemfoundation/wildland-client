
# Simplistic test framework for Wildland HOWTO
#
# Usage: source this file in the test script, like this:
#  . ci/howto-test-lib.bash
#
# Then, prepend each command to be tested with 'run' function, like this:
#   run wl user list
#
# If you want to compare the command output with an expected value, set 'expected' variable first, like this:
#   expected="Some output
#   second line of output"
#   run wl user dump test
#
# For more complex cases, 'expected_pcre' can be used. It will compare the
# output against a PCRE, in a multi-line mode. Note, the '.' normally matches a
# single character only _except newline_. To create a matching any number of
# lines, start the expression with "(?s)" - this will make '.' to match also a
# newline. Non-newline character can still be matched using \N. See
# pcrepattern(3) for more details. Example:
#   expected_pcre="(?s)Some output, then any number of lines
#   .*
#   and finally the last line"
#   run wl user dump test
#
# Helpful pre-made patterns:
#  $USERID_PCRE - matches Wildland user ID
#  $UUID_PCRE - matches any UUID
#
# Helpful functions:
#  - switch_user - switches ~/.config/wildland to another user, stops FUSE if was running
#  - get_userid - get user ID of a given user
#
# You can also set DEBUG=1 in the test, to get a shell when the test fails, and some more info about the failure

set -eo pipefail

. /home/user/env/bin/activate
pip install --no-deps . plugins/*

export PATH=$PATH:$(dirname "$0")/..
alias tree='/usr/bin/tree -A'
export LC_CTYPE=C.UTF-8

test_script=${BASH_SOURCE[-1]}
all_steps=$(grep -c '^run ' "$test_script")
current_step=0

red=$(tput setaf 1 2>/dev/null ||:)
norm=$(tput sgr0 2>/dev/null ||:)
bold=$(tput bold 2>/dev/null ||:)

USERID_PCRE="0x[0-9a-f]{64}"
UUID_PCRE="[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

# run the command, collect its output and, if $expected is set, compare with
# $expected variable content; clear $expected afterwards, to avoid confusion
run() {
    ((++current_step))
    printf '%s(%02d/%02d)%s $ %s%s\n' "$red" $current_step $all_steps "$norm$bold" "$*" "$norm"
    if [ "${expected_fail-0}" = 1 ]; then
        if actual=$("$@" 2>&1); then
            printf '%s\n%s-> SHOULD FAIL%s\n' "$actual" "$red$bold" "$norm"
            if [ "$DEBUG" = 1 ]; then
                bash -i
            fi
            exit 1
        fi
        unset expected_fail
    else
        if ! actual=$("$@" 2>&1); then
            printf '%s\n%s-> FAILED%s\n' "$actual" "$red$bold" "$norm"
            if [ "$DEBUG" = 1 ]; then
                bash -i
            fi
            exit 1
        fi
    fi
    if [ "${expected_pcre-x}" != x ]; then
        expected_pcre=${expected_pcre//
/\\n}
        if ! grep -Pzo -- "$expected_pcre" <(printf '%s' "$actual"); then
            printf '%s\n\n' "$actual"
            printf '%s-> OUTPUT DOES NOT MATCH%s\n' "$red$bold" "$norm"
            if [ "$DEBUG" = 1 ]; then
                set -x
                # make it easy to copy-paste
                expected_pcre="$expected_pcre"
                set -x
                bash -i
            fi
            exit 1
        fi
        unset expected_pcre
    fi
    if [ "${expected-x}" != x ]; then
        if ! diff -u <(printf '%s' "$expected") <(printf '%s' "$actual"); then
            printf '%s-> OUTPUT DOES NOT MATCH%s\n' "$red$bold" "$norm"
            if [ "$DEBUG" = 1 ]; then
                bash -i
            fi
            exit 1
        fi
        unset expected
    fi
    printf '%s\n\n' "$actual"
}

switch_user() {
    new_user="$1"
    current_user=$(wl user dump @default-owner | grep /users/ | cut -f 3 -d /)
    if [ "$new_user" = "$current_user" ]; then
        echo "Already at $new_user" >&2
        return
    fi
    if [ -d ~/.config/wildland-$current_user ]; then
        echo "Something went wrong, ~/.config/wildland-$current_user already exists" >&2
        exit 1
    fi
    wl stop 2>/dev/null || :
    mv -f ~/.config/wildland ~/.config/wildland-$current_user
    if [ -d ~/.config/wildland-$new_user ]; then
        mv -f ~/.config/wildland-$new_user ~/.config/wildland
    else
        mkdir -p ~/.config/wildland
    fi
    echo "Switched user to $new_user"
}

get_userid() {
    wl user dump "$1" | grep owner| cut -f 2 -d :|tr -d " '"
}
