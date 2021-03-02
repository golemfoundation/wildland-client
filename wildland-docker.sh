#!/bin/sh
# a very simple wrapper script for starting up-to-date docker with wildland
cd docker
docker-compose build
docker-compose run --service-ports wildland-client "$@"