#!/usr/bin/env bash

MOUNT_DIR="$HOME/mnt"
mkdir "$MOUNT_DIR"

export __fish_prompt_hostname="wildland-fuse"
cd /wildland-fuse
./wildland-fuse "$MOUNT_DIR" \
  -o manifest=./example/manifests/container1.yaml,manifest=./example/manifests/container2.yaml
cd "$MOUNT_DIR"
exec fish
