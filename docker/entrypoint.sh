#!/bin/bash -e

. /home/user/env/bin/activate

pip install . plugins/*

export EDITOR=vim
export PATH=/home/user/wildland-client:/home/user/wildland-client/docker:$PATH
export __fish_prompt_hostname="$HOSTNAME"
export LC_ALL=C
export XDG_RUNTIME_DIR=/tmp/docker-user-runtime

mkdir -p /tmp/docker-user-runtime

MOUNT_DIR="$HOME/mnt"
mkdir "$MOUNT_DIR"

# workaround for https://github.com/docker/distribution/issues/2853
sudo chmod 666 /dev/fuse

# start apache
sudo /etc/init.d/apache2 start

sudo chown -R user.user ~/.config ~/storage
if ! grep -q '^mount-dir:' ~/.config/wildland/config.yaml 2>/dev/null; then
   # fresh start?
   mkdir -p ~/.config/wildland
   echo "mount-dir: $MOUNT_DIR" >> ~/.config/wildland/config.yaml
fi

cd /home/user

# minimal tmux configuration for FISH as default SHELL
cat > .tmux.conf << EOF
set -g default-command /usr/bin/fish
set -g default-shell /usr/bin/fish
EOF

# minimal screen configuration for FISH as default SHELL
cat > .screenrc << EOF
shell /usr/bin/fish
EOF

ipfs init &> /dev/null
ipfs config Addresses.Gateway "/ip4/127.0.0.1/tcp/8888" # 8080 is already taken

printf "\nWebDAV server is running at dav://localhost:8080/\n\n"

if [ -n "$1" ]; then
    exec "$@"
else
    exec fish
fi
