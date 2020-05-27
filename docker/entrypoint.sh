#!/bin/bash -e

. /home/user/env/bin/activate

export EDITOR=nano
export PATH=/home/user/wildland-fuse:/home/user/wildland-fuse/docker:$PATH

MOUNT_DIR="$HOME/mnt"
mkdir "$MOUNT_DIR"

# workaround for https://github.com/docker/distribution/issues/2853
sudo chmod 666 /dev/fuse

export __fish_prompt_hostname="wildland-fuse"

sudo /etc/init.d/nginx start

sudo chown -R user.user ~/.config ~/.gnupg ~/storage
chmod 0700 ~/.gnupg
if ! [ -f ~/.config/wildland/config.yaml ]; then
   # fresh start?
   mkdir -p ~/.config/wildland
   echo "mount_dir: $MOUNT_DIR" > ~/.config/wildland/config.yaml
fi

cd /home/user

echo
echo "WebDAV server is running at dav://localhost:8080/"
echo "To create example containers, run: wl-example"
echo


if [ -n "$1" ]; then
    exec "$@"
else
    exec fish
fi
