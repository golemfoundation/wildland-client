#!/bin/sh

cd /wildland-fuse
exec pylint wildland/ "$@"
