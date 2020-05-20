#!/bin/bash -e

. /home/user/env/bin/activate

export EDITOR=nano
export PATH=/wildland-fuse:$PATH

MOUNT_DIR="$HOME/mnt"
mkdir "$MOUNT_DIR"

export __fish_prompt_hostname="wildland-fuse"

mkdir -p ~/.config/wildland
echo "mount_dir: $MOUNT_DIR" > ~/.config/wildland/config.yaml

if [ -n "$1" -a -x "docker/$1" ]; then
    cd docker
    exec "$@"
elif [ -n "$1" ]; then
    exec "$@"
else
    ./docker/init.sh
fi
