#!/usr/bin/env python3

import sys
import click

sys.path.insert(0, '..')

from wildland.cli.cli_main import main as cmd_main

def walk_group(cmd, callback, *, prefix=()):
    yield from callback(cmd, prefix)
    if not isinstance(cmd, click.Group):
        return
    prefix = (*prefix, cmd.name)
    for name, subcmd in cmd.commands.items():
        yield from walk_group(subcmd, callback, prefix=prefix)

def joinwalk(cb, group, **kwds):
    return '\n'.join(i or '' for i in walk_group(group, cb, **kwds))

def get_usage(cmd, prefix):
    ctx = click.Context(cmd)
    return ' '.join((*prefix, cmd.name, *cmd.collect_usage_pieces(ctx)))

def format_synopsis(cmd, prefix):
    yield f'| :command:`{get_usage(cmd, prefix)}`'

def format_command(cmd, prefix):
    assert isinstance(cmd, click.Command)
    if isinstance(cmd, click.Group):
        return

    synopsis = f':command:`{get_usage(cmd, prefix)}`'
    name_with_dashes = '-'.join((*prefix, cmd.name))

    yield f'.. program:: {name_with_dashes}'
    yield f'.. _{name_with_dashes}:'
    yield
    yield synopsis
    yield '-' * len(synopsis)
    yield

    for param in cmd.params:
        yield from format_param(param)

def format_param(param):
    if isinstance(param, click.Argument):
        return
    assert isinstance(param, click.Option)

    yield f'.. option:: {", ".join(param.opts)}'
    yield

def format_manpage(group, **kwds):
    return f'''\
*************
manpage title
*************

Synopsis
========

{joinwalk(format_synopsis, group, **kwds)}

Description
===========

.. todo::

   Write general description.

Commands
========

{joinwalk(format_command, group, **kwds)}

'''

def main():
    print(format_manpage(cmd_main))

if __name__ == '__main__':
    main()
