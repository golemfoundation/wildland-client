#!/bin/bash -e
source /home/user/wildland-client/docker/entrypoint.base.sh

echo 127.0.0.1 wildland.local | sudo tee -a /etc/hosts >/dev/null

if [ -n "$1" ]; then
    exec "$@"
else
    echo 'CI must always have something to execute'
    exit 1
fi
