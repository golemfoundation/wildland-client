#!/bin/sh -ex

cd $(dirname $0)

rm -rf /tmp/bla
mkdir /tmp/bla

WL="../../wl"

STORAGE="$HOME/storage"

cp -r storage/* $STORAGE/

$WL user create User

$WL container create container1 --path /container1
$WL storage create local storage11 --location $STORAGE/storage11 \
    --container container1

$WL container create container2 --path /container2
$WL storage create local-cached storage21 --location $STORAGE/storage21 \
    --container container2

cp ~/.config/wildland/containers/container2.container.yaml $STORAGE/storage11/container2.yaml

$WL start --container container1
