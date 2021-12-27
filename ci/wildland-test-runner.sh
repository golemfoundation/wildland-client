#!/usr/bin/env bash

platform=`uname -s | tr "[:upper:]" "[:lower:]"`
if [ "$platform" = "darwin" ]; then
   WL=${WL_CLI}
else
   WL='python3 -m coverage run -p ./wl  --verbose'
fi

testname="$1"
for f in ${testname}-setup-*; do
    if [[ $f = *-common ]] || [[ $f = *-$platform ]]; then
	. $f
    fi
done
. $testname
