#!/bin/sh -e

cd /wildland-fuse
exec pytest "$@"
