#!/bin/bash -e
source /home/user/wildland-client/docker/entrypoint.base.sh

if [ -n "$1" ]; then
    exec "$@"
else
    echo 'CI must always have something to execute'
    exit 1
fi
