#!/bin/bash -e

. /home/user/env/bin/activate

# --no-deps is provided in order to run service in offline mode.
# 'install_requires' such as 'pybear @ git+https://github.com/golemfoundation/pybear#egg=0.0.20200914'
# makes pip requesting network access on startup. This is unsuitable for offline mode.
pip install --no-deps -q . plugins/*

export EDITOR=vim
export PATH=/home/user/wildland-client:/home/user/wildland-client/docker:$PATH
export __fish_prompt_hostname="$HOSTNAME"
export LC_ALL=C.UTF-8
export XDG_RUNTIME_DIR=/tmp/docker-user-runtime

mkdir -p /tmp/docker-user-runtime

MOUNT_DIR="$HOME/wildland"
mkdir "$MOUNT_DIR"

# workaround for https://github.com/docker/distribution/issues/2853
sudo chmod 666 /dev/fuse

# start apache
sudo /etc/init.d/apache2 start

sudo chown -R user.user ~/.config ~/storage
# migration from ~/mnt to ~/wildland
if [ -e ~/.config/wildland/config.yaml ]; then
    sed -i '/^mount-dir: .*\/mnt/d' ~/.config/wildland/config.yaml
fi
if ! grep -q '^mount-dir:' ~/.config/wildland/config.yaml 2>/dev/null; then
    # fresh start?
    mkdir -p ~/.config/wildland
    echo "mount-dir: $MOUNT_DIR" >> ~/.config/wildland/config.yaml
fi

cd /home/user

#
# BEGIN BASH AND FISH CONFIGURATION
#

## BASH
# remove "(env) " prompt prefix when activating venv
sed -i 's/(env) //'  /home/user/env/bin/activate

# modify default PATH too if another one wants to
# open another shell in the running container
cat >> /home/user/.bashrc << EOF
PATH=/home/user/wildland-client:/home/user/wildland-client/docker:$PATH

# it prevents issue when doing fish in fish on venv activation
if test -z "$VIRTUAL_ENV"; then
    source /home/user/env/bin/activate
fi
EOF

mkdir -p /home/user/.config/fish
cat >> /home/user/.config/fish/config.fish << EOF
set -gx PATH /home/user/wildland-client /home/user/wildland-client/docker $PATH

# it prevents issue when doing fish in fish on venv activation
if test -z "$VIRTUAL_ENV"
    source /home/user/env/bin/activate.fish
end
EOF

# minimal screen configuration for default SHELL
cat > .screenrc << EOF
shell /bin/bash
EOF

## FISH
sed -i 's/(env) //'  /home/user/env/bin/activate.fish

mkdir -p /home/user/.config/fish
cat >> /home/user/.config/fish/config.fish << EOF
set -gx PATH /home/user/wildland-client /home/user/wildland-client/docker $PATH

# it prevents issue when doing fish in fish on venv activation
if test -z "$VIRTUAL_ENV"
    source /home/user/env/bin/activate.fish
end
EOF

#cat > .tmux.conf << EOF
#set -g default-command /usr/bin/fish
#set -g default-shell /usr/bin/fish
#EOF

# minimal screen configuration for FISH as default SHELL
#cat > .screenrc << EOF
#shell /usr/bin/fish
#EOF

#
# END CONFIGURATION
#

ipfs init &> /dev/null
ipfs config Addresses.Gateway "/ip4/127.0.0.1/tcp/8888" # 8080 is already taken

printf "\nWebDAV server is running at dav://localhost:8080/\n\n"

if [ -n "$1" ]; then
    exec "$@"
else
    bash
fi
