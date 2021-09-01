#!/bin/bash -e
sudo chown -R user:user ~/.config ~/storage

# Migration from ~/mnt to ~/wildland
if [ -e ~/.config/wildland/config.yaml ]; then
    sed -i '/^mount-dir: .*\/mnt/d' ~/.config/wildland/config.yaml
fi

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
cat > /home/user/.screenrc << EOF
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
#cat > /home/user/.screenrc << EOF
#shell /usr/bin/fish
#EOF

#
# END CONFIGURATION
#

source /home/user/wildland-client/docker/entrypoint.base.sh
printf "\nWebDAV server is running at dav://localhost:8080/\n\n"

# Run IPFS

ipfs init &> /dev/null
ipfs config Addresses.Gateway "/ip4/127.0.0.1/tcp/8888" # 8080 is already taken

if [ -n "$1" ]; then
    exec "$@"
else
    bash
fi
