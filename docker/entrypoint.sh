#!/bin/bash -e

. /home/user/env/bin/activate

pip install . plugins/*

export EDITOR=nano
export PATH=/home/user/wildland-client:/home/user/wildland-client/docker:$PATH

MOUNT_DIR="$HOME/mnt"
mkdir "$MOUNT_DIR"

# workaround for https://github.com/docker/distribution/issues/2853
sudo chmod 666 /dev/fuse

export __fish_prompt_hostname="wildland-client"
export EDITOR=vim

sudo /etc/init.d/apache2 start

sudo /etc/init.d/smbd start

sudo chown -R user.user ~/.config ~/storage
if ! grep -q '^mount-dir:' ~/.config/wildland/config.yaml 2>/dev/null; then
   # fresh start?
   mkdir -p ~/.config/wildland
   echo "mount-dir: $MOUNT_DIR" >> ~/.config/wildland/config.yaml
fi

cd /home/user

echo
echo "WebDAV server is running at dav://localhost:8080/"
echo
echo "SMB server is running at smb://localhost/wildland/"
echo

if [ -n "$1" ]; then
    exec "$@"
else
    exec fish
fi
