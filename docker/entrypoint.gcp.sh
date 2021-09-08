#!/bin/bash -e
mkdir -p /home/user/apache-liveness
echo "<h1>It works""!""</h1><h3>$(hostname)</h3><h3>commit sha:$(cat /home/user/wildland-client/git_commit_sha.txt)</h3>" > /home/user/apache-liveness/index.html

source /home/user/wildland-client/docker/entrypoint.base.sh

# Provision a dummy user if default user is not set

if test -f /home/user/.config/wildland/config.yaml; then
    if test $(cat /home/user/.config/wildland/config.yaml | yq -r '.["@default"]') = "null"; then
        wl u create dummy
    fi
else
    wl u create dummy
fi

# Run IPFS

ipfs init &> /dev/null
ipfs config Addresses.Gateway "/ip4/127.0.0.1/tcp/8888" # 8080 is already taken

if [ -n "$1" ]; then
    exec "$@"
else
    bash
fi
