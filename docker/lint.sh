#!/bin/sh -e

cd /wildland-fuse
exec pylint wildland/ "$@"
