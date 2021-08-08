#!/usr/bin/env bash

testname="$1"
platform=`uname -s | tr "[:upper:]" "[:lower:]"`
for f in ${testname}-setup-*; do
    if [[ $f = *-common ]] || [[ $f = *-$platform ]]; then
	. $f
    fi
done
. $testname
