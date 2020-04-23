#!/bin/sh -e

. /home/user/env/bin/activate

cd /wildland-fuse
exec pylint wildland/ "$@"
