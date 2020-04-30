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
CLI entry point.
'''

import argparse
import sys

from .base import CliError
from . import commands as _commands
from ..log import init_logging
from ..manifest.loader import ManifestLoader


class MainCommand:
    '''
    Main Wildland CLI command that defers to sub-_commands.
    '''

    commands = [
        ('user', 'User management', [
            ('create', 'Create user', _commands.UserCreateCommand()),
            ('list', 'List users', _commands.UserListCommand()),
            ('sign', 'Sign user', _commands.SignCommand('user')),
            ('verify', 'Verify user', _commands.VerifyCommand('user')),
            ('edit', 'Edit user', _commands.EditCommand('user')),
        ]),

        ('storage', 'Storage management', [
            ('create', 'Create stroage', _commands.StorageCreateCommand()),
            ('list', 'List storages', _commands.StorageListCommand()),
            ('sign', 'Sign storage', _commands.SignCommand('storage')),
            ('verify', 'Verify storage', _commands.VerifyCommand('storage')),
            ('edit', 'Edit storage', _commands.EditCommand('storage')),
        ]),

        ('container', 'Container management', [
            ('create', 'Create container', _commands.ContainerCreateCommand()),
            ('update', 'Update container', _commands.ContainerUpdateCommand()),
            ('list', 'List containers', _commands.ContainerListCommand()),
            ('sign', 'Sign container', _commands.SignCommand('container')),
            ('verify', 'Verify container', _commands.VerifyCommand('container')),
            ('edit', 'Edit container', _commands.EditCommand('container')),
            ('mount', 'Mount container', _commands.ContainerMountCommand()),
            ('unmount', 'Unmount container', _commands.ContainerUnmountCommand()),
        ]),

        ('sign', 'Sign manifest', _commands.SignCommand()),
        ('verify', 'Verify manifest', _commands.VerifyCommand()),
        ('edit', 'Edit manifest', _commands.EditCommand()),

        ('mount', 'Mount Wildland filesystem', _commands.MountCommand()),
        ('unmount', 'Unmount Wildland filesystem', _commands.UnmountCommand()),

        ('get', 'Get a file from container', _commands.GetCommand()),
        ('put', 'Put a file in container', _commands.PutCommand()),
    ]

    def __init__(self):
        self.parser = argparse.ArgumentParser()
        self.parser.set_defaults(parser=self.parser, command=None)

        self.add_arguments(self.parser)
        self.add_commands(self.parser, self.commands)

    def add_commands(self, parser, commands):
        '''
        Construct a subcommand tree.
        '''

        subparsers = parser.add_subparsers()
        for name, short, item in commands:
            if isinstance(item, list):
                subparser = subparsers.add_parser(name, help=short)
                subparser.set_defaults(parser=subparser, command=None)
                self.add_commands(subparser, item)
            else:
                command_parser = subparsers.add_parser(
                    name,
                    help=short,
                    description=item.description,
                )
                command_parser.set_defaults(parser=command_parser,
                                            command=item)
                item.add_arguments(command_parser)

    def add_arguments(self, parser):
        # pylint: disable=no-self-use
        '''
        Add common arguments.
        '''

        parser.add_argument(
            '--base-dir',
            help='Base directory for configuration')
        parser.add_argument(
            '--dummy', action='store_true',
            help='Use dummy signatures')
        parser.add_argument(
            '--verbose', '-v', action='count', default=0,
            help='Output logs (repeat for more verbosity)')

    def run(self, cmdline):
        '''
        Entry point.
        '''
        args = self.parser.parse_args(cmdline)
        if args.command:
            loader = ManifestLoader(
                dummy=args.dummy, base_dir=args.base_dir)
            try:
                if args.verbose:
                    level = 'INFO' if args.verbose == 1 else 'DEBUG'
                    init_logging(level=level)
                args.command.setup(loader)
                args.command.handle(args)
            finally:
                loader.close()
        else:
            parser = args.parser
            parser.print_help()


def make_parser():
    '''
    Entry point for Sphinx to parse the commands.
    '''
    return MainCommand().parser


def main(cmdline=None):
    '''
    Wildland CLI entry point.
    '''

    if cmdline is None:
        cmdline = sys.argv[1:]

    try:
        MainCommand().run(cmdline)
    except CliError as e:
        print(f'error: {e}')
        sys.exit(1)


if __name__ == '__main__':
    main()
