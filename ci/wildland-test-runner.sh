#!/usr/bin/env bash

WL='python3 -m coverage run -p ./wl  --verbose'

testname="$1"
platform=`uname -s | tr "[:upper:]" "[:lower:]"`
for f in ${testname}-setup-*; do
    if [[ $f = *-common ]] || [[ $f = *-$platform ]]; then
	. $f
    fi
done
. $testname
