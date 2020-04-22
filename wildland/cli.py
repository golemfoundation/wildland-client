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
Wildland command-line interface.
'''

import argparse
import sys
from typing import Optional, Tuple
import os
import tempfile
import subprocess
import shlex
from pathlib import Path
import copy
import json
import time

import botocore.session
import botocore.credentials

from .manifest.loader import ManifestLoader
from .manifest.manifest import Manifest, ManifestError, HEADER_SEPARATOR, split_header
from .manifest.user import User
from .container import Container
from .exc import WildlandError


PROJECT_PATH = Path(__file__).resolve().parents[1]
FUSE_ENTRY_POINT = PROJECT_PATH / 'wildland-fuse'


class CliError(WildlandError):
    '''
    User error during CLI command execution
    '''

# pylint: disable=no-self-use

class Command:
    '''Base command'''

    def __init__(self):
        self.loader: ManifestLoader = None
        self.mount_dir: Path = None

    @property
    def description(self):
        '''
        Description for this command. By default, taken from class docstring.
        '''
        return self.__class__.__doc__

    def add_arguments(self, parser):
        '''
        Add arguments supported by this command.
        '''

    def setup(self, loader: ManifestLoader):
        '''
        Initialize the command before calling handle().

        The initialization is a separate step, so that we can still read
        command description and call add_arguments() before.
        '''

        self.loader = loader
        self.mount_dir = Path(loader.config.get('mount_dir'))

    def handle(self, args):
        '''
        Run the command based on parsed arguments.
        '''

        raise NotImplementedError()

    def read_manifest_file(self,
                           name: Optional[str],
                           manifest_type: Optional[str]) \
                           -> Tuple[bytes, Optional[Path]]:
        '''
        Read a manifest file specified by name. Recognize None as stdin.

        Returns (data, file_path).
        '''

        if name is None:
            return (sys.stdin.buffer.read(), None)

        path = self.loader.find_manifest(name, manifest_type)
        if not path:
            if manifest_type:
                raise CliError(
                    f'{manifest_type.title()} manifest not found: {name}')
            raise CliError(f'Manifest not found: {name}')
        print(f'Loading: {path}')
        with open(path, 'rb') as f:
            return (f.read(), path)

    def find_user(self, name: Optional[str]) -> User:
        '''
        Find a user specified by name, using default if there is none.
        '''

        if name:
            user = self.loader.find_user(name)
            if not user:
                raise CliError(f'User not found: {name}')
            print(f'Using user: {user.pubkey}')
            return user
        user = self.loader.find_default_user()
        if user is None:
            raise CliError(
                'Default user not set, you need to provide --user')
        print(f'Using default user: {user.pubkey}')
        return user

    def ensure_mounted(self):
        '''
        Check that Wildland is mounted, and raise an exception otherwise.
        '''

        if not os.path.isdir(self.mount_dir / '.control'):
            raise CliError(f'Wildland not mounted at {self.mount_dir}')

    def write_control(self, name: str, data: bytes):
        '''
        Write to a .control file.
        '''

        control_path = self.mount_dir / '.control' / name
        try:
            with open(control_path, 'wb') as f:
                f.write(data)
        except IOError as e:
            raise CliError(f'Control command failed: {control_path}: {e}')

    def read_control(self, name: str) -> bytes:
        '''
        Read a .control file.
        '''

        control_path = self.mount_dir / '.control' / name
        try:
            with open(control_path, 'rb') as f:
                return f.read()
        except IOError as e:
            raise CliError(f'Reading control file failed: {control_path}: {e}')

    def wait_for_mount(self):
        '''
        Wait until Wildland is mounted.
        '''

        n_tries = 20
        delay = 0.1
        for _ in range(n_tries):
            if os.path.isdir(self.mount_dir / '.control'):
                return
            time.sleep(delay)
        raise CliError(f'Timed out waiting for Wildland to mount: {self.mount_dir}')


class UserCreateCommand(Command):
    '''
    Create a new user manifest and save it. You need to have a GPG private key
    in your keyring.
    '''

    def add_arguments(self, parser):
        parser.add_argument(
            'name', nargs='?',
            help='Name for the user')
        parser.add_argument(
            '--key', required=True,
            help='GPG key identifier')

    def handle(self, args):
        pubkey = self.loader.sig.find(args.key)
        print(f'Using key: {pubkey}')

        path = self.loader.create_user(pubkey, args.name)
        print(f'Created: {path}')

        if self.loader.config.get('default_user') is None:
            print(f'Using {pubkey} as default user')
            self.loader.config.update_and_save(default_user=pubkey)


class StorageCreateCommand(Command):
    '''
    Create a new storage manifest.

    The storage has to be associated with a specific container.
    '''

    supported_types = [
        'local',
        's3',
    ]

    def add_arguments(self, parser):
        parser.add_argument(
            'name', nargs='?',
            help='Name for the storage')
        parser.add_argument(
            '--type',
            required=True,
            choices=self.supported_types,
            help='Storage type')
        parser.add_argument(
            '--container', metavar='CONTAINER',
            required=True,
            help='Container this storage is for')
        parser.add_argument(
            '--update-container', '-u', action='store_true',
            help='Update the container after creating storage')
        parser.add_argument(
            '--user',
            help='User for signing')

        parser.add_argument(
            '--path',
            help='Path (for local storage)')
        parser.add_argument(
            '--bucket',
            help='S3 bucket name')

    def handle(self, args):
        if args.type == 'local':
            fields = self.get_fields(args, 'path')
        elif args.type == 's3':
            fields = self.get_fields(args, 'bucket')
            fields['credentials'] = self.get_aws_credentials()
        else:
            assert False, args.type

        self.loader.load_users()
        user = self.find_user(args.user)

        container_path, container_manifest = self.loader.load_manifest(args.container,
                                                        'container')
        if not container_manifest:
            raise CliError(f'Not found: {args.container}')
        container_mount_path = container_manifest.fields['paths'][0]
        print(f'Using container: {container_path} ({container_mount_path})')
        fields['container_path'] = container_mount_path

        storage_path = self.loader.create_storage(user.pubkey, args.type, fields, args.name)
        print('Created: {}'.format(storage_path))

        if args.update_container:
            print('Adding storage to container')
            fields = copy.deepcopy(container_manifest.fields)
            fields['backends']['storage'].append(str(storage_path))
            container_manifest = Manifest.from_fields(fields)
            self.loader.validate_manifest(container_manifest, 'container')
            container_manifest.sign(self.loader.sig)
            signed_data = container_manifest.to_bytes()
            print(f'Saving: {container_path}')
            with open(container_path, 'wb') as f:
                f.write(signed_data)

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

    def get_aws_credentials(self) -> dict:
        '''
        Retrieve AWS credentials.
        '''

        print('Resolving AWS credentials...')
        session = botocore.session.Session()
        resolver = botocore.credentials.create_credential_resolver(session)
        credentials = resolver.load_credentials()
        if not credentials:
            raise CliError("AWS not configured, run 'aws configure' first")
        print(f'Credentials found by method: {credentials.method}')
        return {
            'access_key': credentials.access_key,
            'secret_key': credentials.secret_key,
        }


class ContainerCreateCommand(Command):
    '''
    Create a new container manifest.
    '''

    def add_arguments(self, parser):
        parser.add_argument(
            'name', nargs='?',
            help='Name for the container')
        parser.add_argument(
            '--user',
            help='User for signing')
        parser.add_argument(
            '--path', nargs='+', required=True,
            help='Mount path (can be repeated)')

    def handle(self, args):
        self.loader.load_users()
        user = self.find_user(args.user)
        path = self.loader.create_container(user.pubkey, args.path, args.name)
        print(f'Created: {path}')


class ContainerUpdateCommand(Command):
    '''
    Update a container manifest.
    '''

    def add_arguments(self, parser):
        parser.add_argument(
            'container', metavar='CONTAINER',
            help='Container to modify')
        parser.add_argument(
            '--storage', nargs='*',
            help='Storage to use (can be repeated)')

    def handle(self, args):
        self.loader.load_users()
        path, manifest = self.loader.load_manifest(args.container, 'container')
        if not path:
            raise CliError(f'Container not found: {args.container}')

        if not args.storage:
            print('No change')
            return

        storages = list(manifest.fields['backends']['storage'])
        for storage_name in args.storage:
            storage_path = self.loader.find_manifest(storage_name, 'storage')
            if not storage_path:
                raise CliError(f'Storage manifest not found: {storage_name}')
            print(f'Adding storage: {storage_path}')
            if str(storage_path) in storages:
                raise CliError('Storage already attached to container')
            storages.append(str(storage_path))

        fields = copy.deepcopy(manifest.fields)
        fields['backends']['storage'] = storages
        new_manifest = Manifest.from_fields(fields)
        self.loader.validate_manifest(new_manifest, 'container')
        new_manifest.sign(self.loader.sig)
        signed_data = new_manifest.to_bytes()

        print(f'Saving: {path}')
        with open(path, 'wb') as f:
            f.write(signed_data)


class UserListCommand(Command):
    '''
    Display known users.
    '''

    def handle(self, args):
        self.loader.load_users()
        for user in self.loader.users:
            print('{} {}'.format(user.pubkey, user.manifest_path))


class StorageListCommand(Command):
    '''
    Display known storages.
    '''

    def handle(self, args):
        self.loader.load_users()
        for path, manifest in self.loader.load_manifests('storage'):
            print(path)
            storage_type = manifest.fields['type']
            print(f'  type:', storage_type)
            if storage_type == 'local':
                print(f'  path:', manifest.fields['path'])


class ContainerListCommand(Command):
    '''
    Display known containers.
    '''

    def handle(self, args):
        self.loader.load_users()
        for path, manifest in self.loader.load_manifests('container'):
            print(path)
            for container_path in manifest.fields['paths']:
                print(f'  path:', container_path)
            for storage_path in manifest.fields['backends']['storage']:
                print(f'  storage:', storage_path)


class SignCommand(Command):
    '''
    Sign a manifest. The input file can be a manifest with or without header.
    The existing header will be ignored.

    If invoked with manifest type (``user sign``, etc.), the will also validate
    the manifest against schema.
    '''

    def __init__(self, manifest_type=None):
        super().__init__()
        self.manifest_type = manifest_type

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

    def handle(self, args):
        if args.in_place:
            if not args.input_file:
                raise CliError('Cannot -i without a file')
            if args.output_file:
                raise CliError('Cannot use both -i and -o')

        self.loader.load_users()
        data, path = self.read_manifest_file(args.input_file,
                                             self.manifest_type)

        manifest = Manifest.from_unsigned_bytes(data)
        if self.manifest_type:
            self.loader.validate_manifest(manifest, self.manifest_type)
        manifest.sign(self.loader.sig)
        signed_data = manifest.to_bytes()

        if args.in_place:
            print(f'Saving: {path}')
            with open(path, 'wb') as f:
                f.write(signed_data)
        elif args.output_file:
            print(f'Saving: {args.output_file}')
            with open(args.output_file, 'wb') as f:
                f.write(signed_data)
        else:
            sys.stdout.buffer.write(signed_data)


class VerifyCommand(Command):
    '''
    Verify a manifest signature.

    If invoked with manifests type (``user verify``, etc.), the command will
    also validate the manifest against schema.
    '''

    def __init__(self, manifest_type=None):
        super().__init__()
        self.manifest_type = manifest_type

    def add_arguments(self, parser):
        parser.add_argument(
            'input_file', metavar='FILE', nargs='?',
            help='File to verify (default is stdin)')

    def handle(self, args):
        self.loader.load_users()
        data, _path = self.read_manifest_file(args.input_file,
                                              self.manifest_type)
        try:
            manifest = Manifest.from_bytes(data, self.loader.sig)
            if self.manifest_type:
                self.loader.validate_manifest(manifest, self.manifest_type)
        except ManifestError as e:
            raise CliError(f'Error verifying manifest: {e}')
        print('Manifest is valid')


class EditCommand(Command):
    '''
    Edit and sign a manifest in a safe way. The command will launch an editor
    and validate the edited file before signing and replacing it.

    If invoked with manifests type (``user edit``, etc.), the command will
    also validate the manifest against schema.
    '''

    def __init__(self, manifest_type=None):
        super().__init__()
        self.manifest_type = manifest_type

    def add_arguments(self, parser):
        parser.add_argument(
            'input_file', metavar='FILE',
            help='File to edit')

        parser.add_argument(
            '--editor', metavar='EDITOR',
            help='Editor to use, instead of $EDITOR')

    def handle(self, args):
        if args.editor is None:
            args.editor = os.getenv('EDITOR')
            if args.editor is None:
                raise CliError('No editor specified and EDITOR not set')

        data, path = self.read_manifest_file(args.input_file,
                                             self.manifest_type)

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

        self.loader.load_users()
        manifest = Manifest.from_unsigned_bytes(data)
        if self.manifest_type:
            self.loader.validate_manifest(manifest, self.manifest_type)
        manifest.sign(self.loader.sig)
        signed_data = manifest.to_bytes()
        with open(path, 'wb') as f:
            f.write(signed_data)
        print(f'Saved: {path}')


class MountCommand(Command):
    '''
    Mount the Wildland filesystem. The default path is ``~/wildland/``, but
    it can be customized in the configuration file
    (``~/.widland/config.yaml``) as ``mount_dir``.
    '''

    def add_arguments(self, parser):
        parser.add_argument(
            '--remount', '-r', action='store_true',
            help='If mounted already, remount')

        parser.add_argument(
            '--debug', '-d', action='count',
            default=0,
            help='Debug mode: run in foreground (repeat for more verbosity)')

        parser.add_argument(
            '--container', '-c', metavar='CONTAINER', nargs='*',
            help='Container to mount (can be repeated)')

    def handle(self, args):
        if not os.path.exists(self.mount_dir):
            print(f'Creating: {self.mount_dir}')
            os.makedirs(self.mount_dir)

        if os.path.isdir(self.mount_dir / '.control'):
            if not args.remount:
                raise CliError(f'Already mounted')
            self.unmount()

        cmd = [str(FUSE_ENTRY_POINT), str(self.mount_dir)]
        options = []

        if args.debug > 0:
            options.append('log=-')
            cmd.append('-f')
            if args.debug > 1:
                cmd.append('-d')

        self.loader.load_users()
        to_mount = []
        if args.container:
            for name in args.container:
                path, manifest = self.loader.load_manifest(name, 'container')
                if not manifest:
                    raise CliError(f'Container not found: {name}')
                container = Container(manifest)
                storage_manifest = container.select_storage(self.loader)
                command = {
                    'paths': [str(path) for path in container.paths],
                    'storage': storage_manifest.fields,
                }
                to_mount.append((path, command))

        if options:
            cmd += ['-o', ','.join(options)]

        if args.debug:
            self.run_debug(cmd, to_mount)
        else:
            self.mount(cmd)
            self.mount_containers(to_mount)

    def run_debug(self, cmd, to_mount):
        '''
        Run the FUSE driver in foreground, and cleanup on SIGINT.
        '''

        print(f'Mounting in foreground: {self.mount_dir}')
        print('Press Ctrl-C to unmount')
        # Start a new session in order to not propagate SIGINT.
        p = subprocess.Popen(cmd, start_new_session=True)
        self.wait_for_mount()
        self.mount_containers(to_mount)
        try:
            p.wait()
        except KeyboardInterrupt:
            self.unmount()
            p.wait()

        if p.returncode != 0:
            raise CliError(f'FUSE driver exited with failure')

    def mount(self, cmd):
        '''
        Mount the Wildland filesystem.
        '''

        print(f'Mounting: {self.mount_dir}')
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            raise CliError(f'Failed to unmount: {e}')

    def mount_containers(self, to_mount):
        '''
        Issue a series of .control/mount commands.
        '''

        for path, command in to_mount:
            print(f'Mounting: {path}')
            try:
                with open(self.mount_dir / '.control/mount', 'wb') as f:
                    f.write(json.dumps(command).encode())
            except IOError as e:
                self.unmount()
                raise CliError(f'Failed to mount {path}: {e}')

    def unmount(self):
        '''
        Unmount the Wildland filesystem.
        '''
        print(f'Unmounting: {self.mount_dir}')
        cmd = ['umount', str(self.mount_dir)]
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            raise CliError(f'Failed to unmount: {e}')


class UnmountCommand(Command):
    '''
    Unmount the Wildland filesystem.
    '''

    def handle(self, args):
        print(f'Unmounting: {self.mount_dir}')
        cmd = ['umount', str(self.mount_dir)]
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            raise CliError(f'Failed to unmount: {e}')


class ContainerMountCommand(Command):
    '''
    Mount a container. The Wildland system has to be mounted first, see ``wl
    mount``.
    '''

    def add_arguments(self, parser):
        parser.add_argument(
            'container', metavar='CONTAINER',
            help='Container name or path to manifest')

    def handle(self, args):
        self.ensure_mounted()
        self.loader.load_users()
        path, manifest = self.loader.load_manifest(args.container, 'container')
        if not manifest:
            raise CliError(f'Not found: {args.container}')

        container = Container(manifest)
        storage_manifest = container.select_storage(self.loader)
        command = {
            'paths': container.paths,
            'storage': storage_manifest.fields,
        }

        print(f'Mounting: {path}')
        self.write_control('mount', json.dumps(command).encode())


class ContainerUnmountCommand(Command):
    '''
    Unmount a container. You can either specify the container manifest, or
    identify the container by one of its path (using ``--path``).
    '''

    def add_arguments(self, parser):
        parser.add_argument(
            'container', metavar='CONTAINER', nargs='?',
            help='Container name or path to manifest')
        parser.add_argument(
            '--path', metavar='PATH',
            help='Mount path to search for')

    def handle(self, args):
        self.ensure_mounted()
        self.loader.load_users()

        if bool(args.container) + bool(args.path) != 1:
            raise CliError('Specify either container or --path')

        if args.container:
            num = self.find_by_manifest(args.container)
        else:
            num = self.find_by_path(args.path)
        print(f'Unmounting storage {num}')
        self.write_control('unmount', str(num).encode())

    def find_by_manifest(self, container_name):
        '''
        Find container ID by reading the manifest and matching paths.
        '''

        path, manifest = self.loader.load_manifest(container_name, 'container')
        if not manifest:
            raise CliError(f'Not found: {container_name}')
        print(f'Using manifest: {path}')
        mount_path = manifest.fields['paths'][0]
        return self.find_by_path(mount_path)

    def find_by_path(self, mount_path):
        '''
        Find container ID by one of mount paths.
        '''

        paths = self.read_paths()
        if mount_path not in paths:
            raise CliError(f'No container found under {mount_path}')
        return paths[mount_path]

    def read_paths(self):
        '''Read and parse .control/paths.'''

        return json.loads(self.read_control('paths'))


class MainCommand:
    '''
    Main Wildland CLI command that defers to sub-commands.
    '''

    commands = [
        ('user', 'User management', [
            ('create', 'Create user', UserCreateCommand()),
            ('list', 'List users', UserListCommand()),
            ('sign', 'Sign user', SignCommand('user')),
            ('verify', 'Verify user', VerifyCommand('user')),
            ('edit', 'Edit user', EditCommand('user')),
        ]),

        ('storage', 'Storage management', [
            ('create', 'Create stroage', StorageCreateCommand()),
            ('list', 'List storages', StorageListCommand()),
            ('sign', 'Sign storage', SignCommand('storage')),
            ('verify', 'Verify storage', VerifyCommand('storage')),
            ('edit', 'Edit storage', EditCommand('storage')),
        ]),

        ('container', 'Container management', [
            ('create', 'Create container', ContainerCreateCommand()),
            ('update', 'Update container', ContainerUpdateCommand()),
            ('list', 'List containers', ContainerListCommand()),
            ('sign', 'Sign container', SignCommand('container')),
            ('verify', 'Verify container', VerifyCommand('container')),
            ('edit', 'Edit container', EditCommand('container')),
            ('mount', 'Mount container', ContainerMountCommand()),
            ('unmount', 'Unmount container', ContainerUnmountCommand()),
        ]),

        ('sign', 'Sign manifest', SignCommand()),
        ('verify', 'Verify manifest', VerifyCommand()),
        ('edit', 'Edit manifest', EditCommand()),

        ('mount', 'Mount Wildland filesystem', MountCommand()),
        ('unmount', 'Unmount Wildland filesystem', UnmountCommand()),
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
        '''
        Add common arguments.
        '''

        parser.add_argument(
            '--base-dir',
            help='Base directory for configuration')
        parser.add_argument(
            '--dummy', action='store_true',
            help='Use dummy signatures')

    def run(self, cmdline):
        '''
        Entry point.
        '''
        args = self.parser.parse_args(cmdline)
        if args.command:
            loader = ManifestLoader(
                dummy=args.dummy, base_dir=args.base_dir)
            args.command.setup(loader)
            args.command.handle(args)
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
