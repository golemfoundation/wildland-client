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

import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import time

from typing import Optional, Tuple

import click

from . import __version__ as _version

from .log import init_logging
from . import cli_common, cli_container, cli_storage, cli_user
from .manifest.loader import ManifestLoader
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

class ContextObj:
    '''Helper object for keeping state in :attr:`click.Context.obj`'''

    def __init__(self, loader: ManifestLoader):
        self.loader: ManifestLoader = loader
        self.mount_dir: Path = Path(loader.config.get('mount_dir'))

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
            print(f'Using user: {user.signer}')
            return user
        user = self.loader.find_default_user()
        if user is None:
            raise CliError(
                'Default user not set, you need to provide --user')
        print(f'Using default user: {user.signer}')
        return user

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

    def ensure_mounted(self):
        '''
        Check that Wildland is mounted, and raise an exception otherwise.
        '''

        if not os.path.isdir(self.mount_dir / '.control'):
            raise click.ClickException(
                f'Wildland not mounted at {self.mount_dir}')

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


    def get_command_for_mount_container(self, container):
        '''
        Prepare command to be written to :file:`/.control/mount` to mount
        a container

        Args:
            container (Container): the container to be mounted
        '''
        signer = container.manifest.fields['signer']
        default_user = self.loader.config.get('default_user')

        paths = [
            os.fspath(self.get_user_path(signer, path))
            for path in container.paths
        ]
        if signer is not None and signer == default_user:
            paths.extend(os.fspath(p) for p in container.paths)

        return {
            'paths': paths,
            'storage': container.select_storage(self.loader).fields,
        }

    def get_user_path(self, signer, path: PurePosixPath) -> PurePosixPath:
        '''
        Prepend an absolute path with signer namespace.
        '''
        return PurePosixPath('/.users/') / signer / path.relative_to('/')


@click.group()
@click.option('--dummy/--no-dummy', default=False,
    help='use dummy signatures')
@click.option('--base-dir', default=None,
    help='base directory for configuration')
@click.option('--verbose', '-v', help='output logs')
@click.version_option(_version)
@click.pass_context
def main(ctx, base_dir, dummy, verbose):
    # pylint: disable=missing-docstring
    ctx.obj = ContextObj(ManifestLoader(dummy=dummy, base_dir=base_dir))
    if verbose:
        init_logging()


main.add_command(cli_user.user)
main.add_command(cli_storage.storage)
main.add_command(cli_container.container_)

main.add_command(cli_common.sign)
main.add_command(cli_common.verify)
main.add_command(cli_common.edit)

def _do_mount(cmd):
    '''
    Mount the Wildland filesystem.
    '''
    ctx = click.get_current_context()

    click.echo(f'Mounting {ctx.obj.mount_dir}')
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        raise click.ClickException(f'Failed to unmount: {e}')

def _do_mount_containers(to_mount):
    '''
    Issue a series of .control/mount commands.
    '''
    ctx = click.get_current_context()

    for path, command in to_mount:
        print(f'Mounting: {path}')
        try:
            with open(ctx.obj.mount_dir / '.control/mount', 'wb') as f:
                f.write(json.dumps(command).encode())
        except IOError as e:
            ctx.obj.unmount()
            raise click.ClickException(f'Failed to mount {path}: {e}')


@main.command(short_help='mount Wildland filesystem')
@click.option('--remount', '-r', is_flag=True,
    help='if mounted already, remount')
@click.option('--debug', '-d', count=True,
    help='debug mode: run in foreground (repeat for more verbosity)')
@click.option('--container', '-c', metavar='CONTAINER', multiple=True,
    help='Container to mount (can be repeated)')
@click.pass_context
def mount(ctx, remount, debug, container):
    '''
    Mount the Wildland filesystem. The default path is ``~/wildland/``, but
    it can be customized in the configuration file
    (``~/.widland/config.yaml``) as ``mount_dir``.
    '''

    if not os.path.exists(ctx.obj.mount_dir):
        print(f'Creating: {ctx.obj.mount_dir}')
        os.makedirs(ctx.obj.mount_dir)

    if os.path.isdir(ctx.obj.mount_dir / '.control'):
        if not remount:
            raise CliError(f'Already mounted')
        ctx.obj.unmount()

    cmd = [str(FUSE_ENTRY_POINT), str(ctx.obj.mount_dir)]
    options = []

    if debug > 0:
        options.append('log=-')
        cmd.append('-f')
        if debug > 1:
            cmd.append('-d')

    ctx.obj.loader.load_users()
    to_mount = []
    if container:
        for name in container:
            path, manifest = ctx.obj.loader.load_manifest(name, 'container')
            if not manifest:
                raise CliError(f'Container not found: {name}')
            container = Container(manifest)
            to_mount.append((path,
                ctx.obj.get_command_for_mount_container(container)))

    if options:
        cmd += ['-o', ','.join(options)]

    if not debug:
        _do_mount(cmd)
        _do_mount_containers(to_mount)
        return


    print(f'Mounting in foreground: {ctx.obj.mount_dir}')
    print('Press Ctrl-C to unmount')
    # Start a new session in order to not propagate SIGINT.
    p = subprocess.Popen(cmd, start_new_session=True)
    ctx.obj.wait_for_mount()
    _do_mount_containers(to_mount)
    try:
        p.wait()
    except KeyboardInterrupt:
        ctx.obj.unmount()
        p.wait()

    if p.returncode != 0:
        raise CliError(f'FUSE driver exited with failure')

@main.command(short_help='unmount Wildland filesystem')
@click.pass_context
def unmount(ctx):
    '''
    Unmount the Wildland filesystem.
    '''

    click.echo(f'Unmounting: {ctx.obj.mount_dir}')
    # XXX fusermount?
    cmd = ['umount', os.fspath(ctx.obj.mount_dir)]
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        raise click.ClickException(f'Failed to unmount: {e}')


if __name__ == '__main__':
    main() # pylint: disable=no-value-for-parameter
