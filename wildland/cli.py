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

from .manifest_loader import ManifestLoader
from .manifest import Manifest, ManifestError, HEADER_SEPARATOR, split_header
from .exc import WildlandError
from .user import User


PROJECT_PATH = Path(__file__).resolve().parents[1]
FUSE_ENTRY_POINT = PROJECT_PATH / 'wildland-fuse'


class CliError(WildlandError):
    '''
    User error during CLI command execution
    '''

# pylint: disable=no-self-use

class Command:
    '''Base command'''

    def __init__(self, cmd):
        self.cmd = cmd

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

    def handle(self, loader: ManifestLoader, args):
        '''
        Run the command based on parsed arguments.
        '''

        raise NotImplementedError()

    def read_manifest_file(self,
                           loader: ManifestLoader,
                           name: Optional[str],
                           manifest_type: Optional[str]) \
                           -> Tuple[bytes, Optional[Path]]:
        '''
        Read a manifest file specified by name. Recognize None as stdin.

        Returns (data, file_path).
        '''

        if name is None:
            return (sys.stdin.buffer.read(), None)

        path = loader.find_manifest(name, manifest_type)
        if not path:
            if manifest_type:
                raise CliError(
                    f'{manifest_type.title()} manifest not found: {name}')
            raise CliError(f'Manifest not found: {name}')
        print(f'Loading: {path}')
        with open(path, 'rb') as f:
            return (f.read(), path)

    def find_user(self, loader: ManifestLoader, name: Optional[str]) -> User:
        '''
        Find a user specified by name, using default if there is none.
        '''

        if name:
            user = loader.find_user(name)
            if not user:
                raise CliError(f'User not found: {name}')
            print(f'Using user: {user.pubkey}')
            return user
        user = loader.find_default_user()
        if user is None:
            raise CliError(
                'Default user not set, you need to provide --user')
        print(f'Using default user: {user.pubkey}')
        return user

    def ensure_mounted(self, loader):
        '''
        Check that Wildland is mounted, and raise an exception otherwise.
        '''

        mount_dir = Path(loader.config.get('mount_dir'))
        if not os.path.isdir(mount_dir / '.control'):
            raise CliError(f'Wildland not mounted at {mount_dir}')

    def write_control(self, loader, name: str, data: bytes):
        '''
        Write to a .control file.
        '''

        mount_dir = Path(loader.config.get('mount_dir'))
        control_path = mount_dir / '.control' / name
        try:
            with open(control_path, 'wb') as f:
                f.write(data)
        except IOError as e:
            raise CliError(f'Control command failed: {control_path}: {e}')

    def read_control(self, loader, name: str) -> bytes:
        '''
        Read a .control file.
        '''

        mount_dir = Path(loader.config.get('mount_dir'))
        control_path = mount_dir / '.control' / name
        try:
            with open(control_path, 'rb') as f:
                return f.read()
        except IOError as e:
            raise CliError(f'Reading control file failed: {control_path}: {e}')


class UserCreateCommand(Command):
    '''
    Create a new user manifest and save it. You need to have a GPG private key
    in your keyring.
    '''

    def add_arguments(self, parser):
        parser.add_argument(
            'name',
            help='Name for the user')
        parser.add_argument(
            'key',
            help='GPG key identifier')

    def handle(self, loader, args):
        pubkey = loader.sig.find(args.key)
        print(f'Using key: {pubkey}')

        path = loader.create_user(pubkey, args.name)
        print(f'Created: {path}')

        if loader.config.get('default_user') is None:
            print(f'Using {pubkey} as default user')
            loader.config.update_and_save(default_user=pubkey)


class StorageCreateCommand(Command):
    '''
    Create a new storage manifest.
    '''

    supported_types = [
        'local'
    ]

    def add_arguments(self, parser):
        parser.add_argument(
            'name',
            help='Name for the storage')
        parser.add_argument(
            '--type',
            required=True,
            choices=self.supported_types,
            help='Storage type')
        parser.add_argument(
            '--user',
            help='User for signing')

        parser.add_argument(
            '--path',
            help='Path (for local storage)')

    def handle(self, loader, args):
        if args.type == 'local':
            fields = self.get_fields(args, 'path')
        else:
            assert False, args.type

        loader.load_users()
        user = self.find_user(loader, args.user)

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


class ContainerCreateCommand(Command):
    '''
    Create a new container manifest.
    '''

    def add_arguments(self, parser):
        parser.add_argument(
            'name',
            help='Name for the container')
        parser.add_argument(
            '--user',
            help='User for signing')
        parser.add_argument(
            '--path', nargs='+', required=True,
            help='Mount path (can be repeated)')
        parser.add_argument(
            '--storage', nargs='+', required=True,
            help='Storage to use (can be repeated)')


    def handle(self, loader, args):
        loader.load_users()
        user = self.find_user(loader, args.user)
        storages = []
        for storage_name in args.storage:
            storage_path = loader.find_manifest(storage_name, 'storage')
            if not storage_path:
                raise CliError(f'Storage manifest not found: {storage_name}')
            print(f'Using storage: {storage_path}')
            storages.append(str(storage_path))
        path = loader.create_container(user.pubkey, args.path, storages,
                                       args.name)
        print(f'Created: {path}')


class UserListCommand(Command):
    '''
    Display known users.
    '''

    def handle(self, loader, args):
        loader.load_users()
        for user in loader.users:
            print('{} {}'.format(user.pubkey, user.manifest_path))


class StorageListCommand(Command):
    '''
    Display known storages.
    '''

    def handle(self, loader, args):
        loader.load_users()
        for path, manifest in loader.load_manifests('storage'):
            print(path)
            storage_type = manifest.fields['type']
            print(f'  type:', storage_type)
            if storage_type == 'local':
                print(f'  path:', manifest.fields['path'])


class ContainerListCommand(Command):
    '''
    Display known containers.
    '''

    def handle(self, loader, args):
        loader.load_users()
        for path, manifest in loader.load_manifests('container'):
            print(path)
            for container_path in manifest.fields['paths']:
                print(f'  path:', container_path)


class SignCommand(Command):
    '''
    Sign a manifest. The input file can be a manifest with or without header.
    The existing header will be ignored.

    If invoked with manifest type (``user-sign``, etc.), the will also validate
    the manifest against schema.
    '''

    def __init__(self, cmd, manifest_type=None):
        super().__init__(cmd)
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

    def handle(self, loader, args):
        if args.in_place:
            if not args.input_file:
                raise CliError('Cannot -i without a file')
            if args.output_file:
                raise CliError('Cannot use both -i and -o')

        loader.load_users()
        data, path = self.read_manifest_file(loader, args.input_file,
                                             self.manifest_type)

        manifest = Manifest.from_unsigned_bytes(data)
        loader.validate_manifest(manifest, self.manifest_type)
        manifest.sign(loader.sig)
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

    If invoked with manifests type (``user-verify etc.``), the command will
    also validate the manifest against schema.
    '''

    def __init__(self, cmd, manifest_type=None):
        super().__init__(cmd)
        self.manifest_type = manifest_type

    def add_arguments(self, parser):
        parser.add_argument(
            'input_file', metavar='FILE', nargs='?',
            help='File to verify (default is stdin)')

    def handle(self, loader, args):
        loader.load_users()
        data, _path = self.read_manifest_file(loader, args.input_file,
                                              self.manifest_type)
        try:
            manifest = Manifest.from_bytes(data, loader.sig)
            loader.validate_manifest(manifest, self.manifest_type)
        except ManifestError as e:
            raise CliError(f'Error verifying manifest: {e}')
        print('Manifest is valid')


class EditCommand(Command):
    '''
    Edit and sign a manifest in a safe way. The command will launch an editor
    and validate the edited file before signing and replacing it.

    If invoked with manifests type (``user-edit etc.``), the command will
    also validate the manifest against schema.
    '''

    def __init__(self, cmd, manifest_type=None):
        super().__init__(cmd)
        self.manifest_type = manifest_type

    def add_arguments(self, parser):
        parser.add_argument(
            'input_file', metavar='FILE',
            help='File to edit')

        parser.add_argument(
            '--editor', metavar='EDITOR',
            help='Editor to use, instead of $EDITOR')

    def handle(self, loader, args):
        if args.editor is None:
            args.editor = os.getenv('EDITOR')
            if args.editor is None:
                raise CliError('No editor specified and EDITOR not set')

        data, path = self.read_manifest_file(loader, args.input_file,
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

        loader.load_users()
        manifest = Manifest.from_unsigned_bytes(data)
        loader.validate_manifest(manifest, self.manifest_type)
        manifest.sign(loader.sig)
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

    def handle(self, loader, args):
        mount_dir = loader.config.get('mount_dir')
        if not os.path.exists(mount_dir):
            print(f'Creating: {mount_dir}')
            os.makedirs(mount_dir)
        print(f'Mounting: {mount_dir}')

        options = ['base_dir=' + str(loader.config.base_dir)]
        if loader.config.get('dummy'):
            options.append('dummy_sig')
        cmd = [str(FUSE_ENTRY_POINT), str(mount_dir), '-o', ','.join(options)]
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            raise CliError(f'Failed to mount: {e}')


class UnmountCommand(Command):
    '''
    Unmount the Wildland filesystem.
    '''

    def handle(self, loader, args):
        mount_dir = loader.config.get('mount_dir')
        cmd = ['umount', str(mount_dir)]
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

    def handle(self, loader, args):
        self.ensure_mounted(loader)
        loader.load_users()
        path, manifest = loader.load_manifest(args.container, 'container')
        if not manifest:
            raise CliError(f'Not found: {args.container}')
        print(f'Mounting: {path}')
        self.write_control(loader, 'mount', manifest.to_bytes())


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

    def handle(self, loader, args):
        self.ensure_mounted(loader)
        loader.load_users()

        if bool(args.container) + bool(args.path) != 1:
            raise CliError('Specify either container or --path')

        if args.container:
            num = self.find_by_manifest(loader, args.container)
        else:
            num = self.find_by_path(loader, args.path)
        print(f'Unmounting container {num}')
        self.write_control(loader, 'cmd', f'unmount {num}'.encode())

    def find_by_manifest(self, loader, container_name):
        '''
        Find container ID by reading the manifest and matching paths.
        '''

        path, manifest = loader.load_manifest(container_name, 'container')
        if not manifest:
            raise CliError(f'Not found: {container_name}')
        print(f'Using manifest: {path}')
        nums = set()
        for path, num in self.read_paths(loader):
            if path in manifest.fields['paths']:
                nums.add(num)

        if len(nums) == 0:
            raise CliError(
                'Container with a given list of paths not found. '
                'Is it mounted?')
        if len(nums) > 1:
            raise CliError(
                'More than one container found: {}. '
                'Consider unmounting by path instead.'.format(
                    ', '.join(map(str, nums))))

        return list(nums)[0]

    def find_by_path(self, loader, container_path):
        '''
        Find container ID by one of mount paths.
        '''

        for path, num in self.read_paths(loader):
            print(path)
            if container_path == path:
                return num
        raise CliError(f'No container found: {container_path}')

    def read_paths(self, loader):
        '''Read and parse .control/paths.'''

        for line in self.read_control(loader, 'paths').decode().splitlines():
            path, _sep, num = line.rpartition(' ')
            yield path, num


class MainCommand:
    '''
    Main Wildland CLI command that defers to sub-commands.
    '''

    commands = [
        UserCreateCommand('user-create'),
        UserListCommand('user-list'),
        SignCommand('user-sign', 'user'),
        VerifyCommand('user-verify', 'user'),
        EditCommand('user-edit', 'user'),

        StorageCreateCommand('storage-create'),
        StorageListCommand('storage-list'),
        SignCommand('storage-sign', 'storage'),
        VerifyCommand('storage-verify', 'storage'),
        EditCommand('storage-edit', 'storage'),

        ContainerCreateCommand('container-create'),
        ContainerListCommand('container-list'),
        SignCommand('container-sign', 'container'),
        VerifyCommand('container-verify', 'container'),
        EditCommand('container-edit', 'container'),
        ContainerMountCommand('container-mount'),
        ContainerUnmountCommand('container-unmount'),

        SignCommand('sign'),
        VerifyCommand('verify'),
        EditCommand('edit'),

        MountCommand('mount'),
        UnmountCommand('unmount'),
    ]

    def __init__(self):
        self.parser = argparse.ArgumentParser()
        self.add_arguments(self.parser)
        subparsers = self.parser.add_subparsers(dest='cmd')
        for command in self.commands:
            command_parser = subparsers.add_parser(
                command.cmd,
                description=command.description,
            )
            command.add_arguments(command_parser)

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
