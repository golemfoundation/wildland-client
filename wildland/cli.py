'''
Wildland command-line interface.
'''

import argparse
import sys
from typing import Optional
import os
import tempfile
import subprocess
import shlex
from pathlib import Path

from .manifest_loader import ManifestLoader
from .manifest import Manifest, ManifestError, HEADER_SEPARATOR, split_header
from .exc import WildlandError

class CliError(WildlandError):
    '''
    User error during CLI command execution
    '''

# pylint: disable=no-self-use

class Command:
    '''Base command'''

    cmd: str = ''

    def __init__(self, subparsers):
        self.parser = subparsers.add_parser(self.cmd,
                                            help=self.__class__.__doc__)
        self.add_arguments(self.parser)

    def add_arguments(self, parser):
        '''
        Add arguments supported by this command.
        '''

    def handle(self, loader: ManifestLoader, args):
        '''
        Run the command based on parsed arguments.
        '''

        raise NotImplementedError()


class UserCreateCommand(Command):
    '''Create a new user'''

    cmd = 'user-create'

    def add_arguments(self, parser):
        parser.add_argument(
            'key',
            help='GPG key identifier')
        parser.add_argument(
            '--name',
            help='Name for file')

    def handle(self, loader, args):
        pubkey = loader.sig.find(args.key)
        print('Using key: {}'.format(pubkey))

        path = loader.create_user(pubkey, args.name)
        print('Created: {}'.format(path))


class StorageCreateCommand(Command):
    '''Create a new storage'''

    cmd = 'storage-create'

    supported_types = [
        'local'
    ]

    def add_arguments(self, parser):
        parser.add_argument(
            '--type',
            required=True,
            choices=self.supported_types,
            help='Storage type')
        parser.add_argument(
            '--user', required=True,
            help='User for signing')
        parser.add_argument(
            '--name',
            help='Name for file')

        parser.add_argument(
            '--path',
            help='Path (for local storage)')

    def handle(self, loader, args):
        if args.type == 'local':
            fields = self.get_fields(args, 'path')
        else:
            assert False, args.type

        user = loader.find_user(args.user)
        print('Using user: {}'.format(user.pubkey))

        path = loader.create_storage(user.pubkey, args.type, fields, args.name)
        print('Created: {}'.format(path))

    def get_fields(self, args, *names) -> dict:
        '''
        Create a dict of fields from required arguments.
        '''
        fields = {}
        for name in names:
            if not getattr(args, name):
                raise CliError('Expecting the following fields: {}'.format(
                    ', '.join(names)))
            fields[name] = getattr(args, name)
        return fields


class UserListCommand(Command):
    '''List users'''

    cmd = 'user-list'

    def handle(self, loader, args):
        loader.load_users()
        for user in loader.users:
            print('{} {}'.format(user.pubkey, user.manifest_path))


class SignCommand(Command):
    '''Sign a manifest'''
    cmd = 'sign'
    manifest_type: Optional[str] = None

    def add_arguments(self, parser):
        parser.add_argument(
            'input_file', metavar='FILE', nargs='?',
            help='File to sign (default is stdin)')
        parser.add_argument(
            '-o', dest='output_file', metavar='FILE',
            help='Output file (default is stdout)')
        parser.add_argument(
            '-i', dest='in_place', action='store_true',
            help='Modify the file in place')

    def handle(self, loader, args):
        loader.load_users()
        data = self.load(loader, args)
        manifest = Manifest.from_unsigned_bytes(data)
        loader.validate_manifest(manifest, self.manifest_type)
        manifest.sign(loader.sig)
        signed_data = manifest.to_bytes()
        self.save(args, signed_data)

    def load(self, loader, args) -> bytes:
        '''
        Load from file or stdin.
        '''
        if args.input_file:
            path = loader.find_manifest(args.input_file, self.manifest_type)
            if args.in_place:
                if args.output_file:
                    raise CliError('Cannot use both -i and -o')
                args.output_file = path
            with open(path, 'rb') as f:
                return f.read()

        if args.in_place:
            if not args.input_file:
                raise CliError('Cannot -i without a file')
        return sys.stdin.buffer.read()

    def save(self, args, data: bytes):
        '''
        Save to file or stdout.
        '''

        if args.output_file:
            with open(args.output_file, 'wb') as f:
                f.write(data)
            print(f'Saved: {args.output_file}')
        else:
            sys.stdout.buffer.write(data)


class VerifyCommand(Command):
    '''Verify a manifest'''
    cmd = 'verify'
    manifest_type: Optional[str] = None

    def add_arguments(self, parser):
        parser.add_argument(
            'input_file', metavar='FILE', nargs='?',
            help='File to verify (default is stdin)')

    def handle(self, loader, args):
        loader.load_users()
        data = self.load(loader, args)
        try:
            manifest = Manifest.from_bytes(data, loader.sig)
            loader.validate_manifest(manifest, self.manifest_type)
        except ManifestError as e:
            raise CliError(f'Error verifying manifest: {e}')
        print('Manifest is valid')

    def load(self, loader, args) -> bytes:
        '''
        Load from file or stdin.
        '''

        if args.input_file:
            path = loader.find_manifest(args.input_file, self.manifest_type)
            with open(path, 'rb') as f:
                return f.read()
        return sys.stdin.buffer.read()


class EditCommand(Command):
    '''Edit and sign a manifest'''
    cmd = 'edit'
    manifest_type: Optional[str] = None

    def add_arguments(self, parser):
        parser.add_argument(
            'input_file', metavar='FILE',
            help='File to edit')

        parser.add_argument(
            '--editor', metavar='EDITOR',
            help='Editor to use')

    def handle(self, loader, args):
        if args.editor is None:
            args.editor = os.getenv('EDITOR')
            if args.editor is None:
                raise CliError('No editor specified and EDITOR not set')

        path = loader.find_manifest(args.input_file, self.manifest_type)
        with open(path, 'rb') as f:
            data = f.read()

        if HEADER_SEPARATOR in data:
            _, data = split_header(data)

        # Do not use NamedTemporaryFile, because the editor might create a new
        # file instead modifying the existing one.
        with tempfile.TemporaryDirectory(prefix='wledit.') as temp_dir:
            temp_path = Path(temp_dir) / path.name
            with open(temp_path, 'wb') as f:
                f.write(data)

            command = '{} {}'.format(
                args.editor, shlex.quote(f.name))
            print(f'Running editor: {command}')
            try:
                subprocess.run(command, shell=True, check=True)
            except subprocess.CalledProcessError:
                raise CliError('Running editor failed')

            with open(temp_path, 'rb') as f:
                data = f.read()

        loader.load_users()
        manifest = Manifest.from_unsigned_bytes(data)
        loader.validate_manifest(manifest, self.manifest_type)
        manifest.sign(loader.sig)
        signed_data = manifest.to_bytes()
        with open(path, 'wb') as f:
            f.write(signed_data)
        print(f'Saved: {path}')


class UserSignCommand(SignCommand):
    '''Verify a user manifest'''
    cmd = 'user-sign'
    manifest_type = 'user'


class UserVerifyCommand(VerifyCommand):
    '''Verify a user manifest'''
    cmd = 'user-verify'
    manifest_type = 'user'


class UserEditCommand(EditCommand):
    '''Edit a user manifest'''
    cmd = 'user-edit'
    manifest_type = 'user'


class StorageSignCommand(SignCommand):
    '''Sign a storage manifest'''
    cmd = 'storage-sign'
    manifest_type = 'storage'


class StorageVerifyCommand(VerifyCommand):
    '''Verify a storage manifest'''
    cmd = 'storage-verify'
    manifest_type = 'storage'


class StorageEditCommand(EditCommand):
    '''Edit a storage manifest'''
    cmd = 'storage-edit'
    manifest_type = 'storage'


class MainCommand:
    '''
    Main Wildland CLI command that defers to sub-commands.
    '''

    command_classes = [
        UserCreateCommand,
        UserListCommand,
        UserSignCommand,
        UserVerifyCommand,
        UserEditCommand,

        StorageCreateCommand,
        StorageSignCommand,
        StorageVerifyCommand,
        StorageEditCommand,

        SignCommand,
        VerifyCommand,
        EditCommand,
    ]

    def __init__(self):
        self.parser = argparse.ArgumentParser()
        self.add_arguments(self.parser)
        subparsers = self.parser.add_subparsers(dest='cmd')
        self.commands = []
        for command_cls in self.command_classes:
            command = command_cls(subparsers)
            self.commands.append(command)

    def add_arguments(self, parser):
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
            '--gpg-home',
            help='Use a different GPG home directory')

    def run(self, cmdline):
        '''
        Entry point.
        '''
        args = self.parser.parse_args(cmdline)

        loader = ManifestLoader(
            dummy=args.dummy, base_dir=args.base_dir, gpg_home=args.gpg_home)

        for command in self.commands:
            if args.cmd == command.cmd:
                command.handle(loader, args)
                return
        self.parser.print_help()


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
