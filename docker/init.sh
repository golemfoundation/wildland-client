#!/usr/bin/env bash

MOUNT_DIR="$HOME/mnt"
mkdir "$MOUNT_DIR"

export __fish_prompt_hostname="wildland-fuse"
cd /wildland-fuse

mkdir -p ~/.wildland
echo "mount_dir: $MOUNT_DIR" > ~/.wildland/config.yaml

./example/setup.sh

cd "$MOUNT_DIR"
exec fish
