#!/usr/bin/env bash

MOUNT_DIR="$HOME/mnt"
export EDITOR=nano
export PATH=/wildland-fuse:$PATH

mkdir "$MOUNT_DIR"

export __fish_prompt_hostname="wildland-fuse"

mkdir -p ~/.config/wildland
echo "mount_dir: $MOUNT_DIR" > ~/.config/wildland/config.yaml

/wildland-fuse/example/setup.sh

cd "$MOUNT_DIR"
exec fish
