#!/bin/bash -e

. /home/user/env/bin/activate

pip install . plugins/*

export EDITOR=nano
export PATH=/home/user/wildland-fuse:/home/user/wildland-fuse/docker:$PATH

MOUNT_DIR="$HOME/mnt"
mkdir "$MOUNT_DIR"

# workaround for https://github.com/docker/distribution/issues/2853
sudo chmod 666 /dev/fuse

export __fish_prompt_hostname="wildland-fuse"

sudo /etc/init.d/apache2 start

sudo chown -R user.user ~/.config ~/storage
if ! [ -f ~/.config/wildland/config.yaml ]; then
   # fresh start?
   mkdir -p ~/.config/wildland
   echo "mount-dir: $MOUNT_DIR" > ~/.config/wildland/config.yaml
fi

cd /home/user

echo
echo "WebDAV server is running at dav://localhost:8080/"
echo


if [ -n "$1" ]; then
    exec "$@"
else
    exec fish
fi
