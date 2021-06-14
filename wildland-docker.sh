#!/bin/sh -e
# a very simple wrapper script for starting up-to-date docker with wildland

localdir="$(readlink -f "$(dirname "$0")")"
cd "$localdir/docker"

# build docker services
docker-compose build

# run wildland-client service
docker-compose run --service-ports wildland-client "$@"
