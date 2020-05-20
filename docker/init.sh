#!/bin/bash -e

/wildland-fuse/example/setup.sh

cd "$MOUNT_DIR"
exec fish
