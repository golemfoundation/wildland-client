#!/bin/sh -ex

cd $(dirname $0)

rm -rf /tmp/bla
mkdir /tmp/bla

WL="../wl"

gpg2 --import test-secret-key.key

cp -r storage /tmp/storage

$WL user create User --key "Test Key"

$WL container create container1 --path /container1
$WL storage create local storage11 --path /tmp/storage/storage11 \
    --container container1 --update-container

$WL container create container2 --path /container2
$WL storage create local-cached storage21 --path /tmp/storage/storage21 \
    --container container2 --update-container

cp ~/.config/wildland/containers/container2.yaml /tmp/storage/storage11/container2.yaml

$WL mount --container container1
