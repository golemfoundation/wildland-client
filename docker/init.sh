#!/usr/bin/env bash

export __fish_prompt_hostname="wildland-fuse"
cd /wildland-fuse
/sbin/mount.fuse ./wildland-fuse /mnt \
  -o manifest=./example/manifests/container1.yaml,manifest=./example/manifests/container2.yaml
cd /mnt
fish
