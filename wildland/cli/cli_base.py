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

"""
Wildland command-line interface - base module.
"""

import collections
import sys
import traceback
from pathlib import Path
from typing import List, Tuple, Callable

import click

from ..exc import WildlandError
from ..client import Client


class CliError(WildlandError, click.ClickException):
    """
    User error during CLI command execution
    """

# pylint: disable=no-self-use


class ContextObj:
    """Helper object for keeping state in :attr:`click.Context.obj`"""

    def __init__(self, client: Client):
        self.fs_client = client.fs_client
        self.mount_dir: Path = client.fs_client.mount_dir
        self.client = client
        self.session = client.session


class AliasedGroup(click.Group):
    """A very simple alias engine for :class:`click.Group`"""

    def __init__(self, *args, **kwds):
        super().__init__(*args, **kwds)
        self.aliases = {}
        self.debug = False

    def __call__(self, *args, **kwargs):
        try:
            return self.main(*args, **kwargs)
        except Exception as exc:
            click.echo(f'Error: {exc}')
            if self.debug is True:
                traceback.print_exception(*sys.exc_info())

            if isinstance(exc, click.ClickException):
                # pylint: disable=no-member
                sys.exit(exc.exit_code)
            else:
                sys.exit(1)

    def command(self, *args, **kwargs):
        if 'alias' not in kwargs:
            return super().command(*args, **kwargs)

        aliases = kwargs.pop('alias')
        super_decorator = super().command(*args, **kwargs)

        def decorator(f):
            cmd = super_decorator(f)
            self.add_alias(**{alias: cmd.name for alias in aliases})
            return cmd

        return decorator

    def add_alias(self, **kwds):
        """Add aliases to a command

        >>> cmd.add_alias(alias='original-command')
        """
        assert all(
            alias not in (*self.aliases, *self.commands) for alias in kwds)
        self.aliases.update(kwds)

    def get_command(self, ctx, cmd_name):
        if self.name == 'wl':
            self.debug = ctx.params['debug']

        # 1) try exact command
        rv = super().get_command(ctx, cmd_name)
        if rv is not None:
            return rv

        # 2) try exact alias
        if cmd_name in self.aliases:
            return super().get_command(ctx, self.aliases[cmd_name])

        # 3) try unambiguous prefix in both commands and aliases
        matches: List[Tuple[str, bool]] = []
        matches.extend((cn, False)
            for cn in self.list_commands(ctx) if cn.startswith(cmd_name))
        matches.extend((an, True)
            for an in self.aliases if an.startswith(cmd_name))

        if len(matches) == 0:
            return None

        if len(matches) > 1:
            desc = ', '.join(
                f'{name} ({"alias" if is_alias else "command"})'
                for (name, is_alias) in matches)
            ctx.fail(f'too many matches: {desc}')

        name, is_alias = matches[0]
        if is_alias:
            name = self.aliases[name]

        click.echo(f'Understood {cmd_name!r} as {name!r}')
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


def aliased_group(name=None, **kwargs) -> Callable[[Callable], AliasedGroup]:
    """
    A decorator that creates an AliasedGroup and typechecks properly.
    """

    def decorator(f):
        return click.group(name, cls=AliasedGroup, **kwargs)(f)

    return decorator
