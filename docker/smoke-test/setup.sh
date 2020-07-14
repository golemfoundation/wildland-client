#!/bin/sh -ex

cd $(dirname $0)

rm -rf /tmp/bla
mkdir /tmp/bla

WL="../../wl"

STORAGE="$HOME/storage"

cp -r storage/* $STORAGE/

$WL user create User

$WL container create container1 --path /container1
$WL storage create local storage11 --path $STORAGE/storage11 \
    --container container1 --update-container

$WL container create container2 --path /container2
$WL storage create local-cached storage21 --path $STORAGE/storage21 \
    --container container2 --update-container

cp ~/.config/wildland/containers/container2.yaml $STORAGE/storage11/container2.yaml

$WL start --container container1
