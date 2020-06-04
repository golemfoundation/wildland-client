# Wildland Project
#
# Copyright (C) 2020 Golem Foundation,
#                    Paweł Marczewski <pawel@invisiblethingslab.com>,
#                    Wojtek Porczyk <woju@invisiblethingslab.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

'''
Wildland command-line interface - base module.
'''

import collections
from pathlib import Path

import click

from ..exc import WildlandError
from ..client import Client


class CliError(WildlandError):
    '''
    User error during CLI command execution
    '''

# pylint: disable=no-self-use


class ContextObj:
    '''Helper object for keeping state in :attr:`click.Context.obj`'''

    def __init__(self, client: Client):
        self.fs_client = client.fs_client
        self.mount_dir: Path = client.fs_client.mount_dir
        self.client = client
        self.session = client.session

class AliasedGroup(click.Group):
    '''A very simple alias engine for :class:`click.Group`'''

    def __init__(self, *args, **kwds):
        super().__init__(*args, **kwds)
        self.aliases = {}

    def add_alias(self, **kwds):
        '''Add aliases to a command

        >>> cmd.add_alias(alias='original-command')
        '''
        assert all(
            alias not in (*self.aliases, *self.commands) for alias in kwds)
        self.aliases.update(kwds)

    def get_command(self, ctx, cmd_name):
        # 1) try exact command
        rv = super().get_command(ctx, cmd_name)
        if rv is not None:
            return rv

        # 2) try exact alias
        try:
            aliased_name = self.aliases[cmd_name]
        except KeyError:
            pass
        else:
            return super().get_command(ctx, aliased_name)

        # 3) try unambiguous prefix in both commands and aliases
        matches = []
        matches.extend((cn, False)
            for cn in self.list_commands(ctx) if cn.startswith(cmd_name))
        matches.extend((an, True)
            for an in self.aliases if an.startswith(cmd_name))

        print(f'matches={matches!r}')

        if not matches:
            return
        elif len(matches) > 1:
            matches = ', '.join(
                f'{name} ({is_alias and "alias" or "command"})')
            ctx.fail(f'too many matches: {matches}')

        (name, is_alias), = matches
        if is_alias:
            name = self.aliases[name]
        print(f'cmd_name={cmd_name!r}')
        return super().get_command(ctx, name)

    def format_commands(self, ctx, formatter):
        super().format_commands(ctx, formatter)
        if not self.aliases:
            return

        aliases_reversed = collections.defaultdict(set)
        for alias, cmd_name in self.aliases.items():
            aliases_reversed[cmd_name].add(alias)

        with formatter.section('Aliases'):
            formatter.write_dl((cmd_name, ', '.join(sorted(aliases_reversed[cmd_name])))
                for cmd_name in sorted(aliases_reversed))
