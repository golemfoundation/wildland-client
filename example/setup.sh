#!/bin/sh -ex

cd $(dirname $0)

rm -rf /tmp/bla
mkdir /tmp/bla

WL="../wl"

gpg2 --import test-secret-key.key

$WL user create User "Test Key"

$WL container create container1 --path /container1
$WL storage create storage11 --type local --path $(realpath storage/storage11) \
    --container container1 --update-container

$WL container create container2 --path /container2
$WL storage create storage21 --type local --path $(realpath storage/storage21) \
    --container container2 --update-container

$WL mount --container container1 container2
