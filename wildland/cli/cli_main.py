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
Wildland command-line interface.
"""

import os
from pathlib import Path

import click

from wildland.exc import WildlandError
from wildland.wildland_object.wildland_object import WildlandObject
from .cli_base import (
    aliased_group,
    CliError,
    ContextObj,
)
from . import (
    cli_common,
    cli_user,
    cli_forest,
    cli_storage,
    cli_storage_template,
    cli_container,
    cli_bridge,
    cli_transfer,
)

from ..log import init_logging
from ..manifest.manifest import ManifestError
from ..client import Client
from .. import __version__ as _version


PROJECT_PATH = Path(__file__).resolve().parents[1]
FUSE_ENTRY_POINT = PROJECT_PATH / 'wildland-fuse'


@aliased_group('wl')
@click.option('--dummy/--no-dummy', default=False,
              help='use dummy signatures')
@click.option('--base-dir', default=None,
              help='base directory for configuration')
@click.option('--debug/--no-debug', default=False,
              help='print full traceback on exception')
@click.option('--verbose', '-v', count=True,
              help='output logs (repeat for more verbosity)')
@click.version_option(_version)
@click.pass_context
def main(ctx: click.Context, base_dir, dummy, debug, verbose):
    # pylint: disable=missing-docstring, unused-argument

    client = Client(dummy=dummy, base_dir=base_dir)
    ctx.obj = ContextObj(client)
    if verbose > 0:
        init_logging(level='DEBUG' if verbose > 1 else 'INFO')


main.add_command(cli_user.user_)
main.add_command(cli_forest.forest_)
main.add_command(cli_storage.storage_)
main.add_command(cli_storage_template.storage_template)
main.add_command(cli_container.container_)
main.add_command(cli_bridge.bridge_)
main.add_alias(users='user', u='user', storages='storage', s='storage', containers='container',
               c='container', bridges='bridge', b='bridge')

main.add_command(cli_common.sign)
main.add_command(cli_common.verify)
main.add_command(cli_common.edit)
main.add_command(cli_common.dump)

main.add_command(cli_transfer.get)
main.add_command(cli_transfer.put)


def _do_mount_containers(obj: ContextObj, to_mount):
    """
    Issue a series of .control/mount commands.
    """
    if not to_mount:
        return

    fs_client = obj.fs_client
    failed = []
    commands = []
    for name in to_mount:
        click.echo(f'Resolving containers: {name}')
        containers = obj.client.load_containers_from(name)
        reordered, _, _ = obj.client.ensure_mount_reference_container(containers)
        for container in reordered:
            user_paths = obj.client.get_bridge_paths_for_user(container.owner)
            try:
                commands.extend(cli_container.prepare_mount(
                    obj, container, str(container.local_path), user_paths,
                    remount=False, with_subcontainers=True, subcontainer_of=None, verbose=False,
                    only_subcontainers=False))
            except WildlandError as we:
                failed.append(f'Container {name} cannot be mounted: {we}')
                continue

    click.echo(f'Mounting {len(commands)} containers.')

    try:
        fs_client.mount_multiple_containers(commands)
    except WildlandError as e:
        failed.append(f'Failed to mount: {e}')

    if failed:
        click.echo('Non-critical error(s) occurred:\n' + "\n".join(failed))


@main.command(short_help='mount Wildland filesystem')
@click.option('--remount', '-r', is_flag=True,
    help='if mounted already, remount')
@click.option('--debug', '-d', count=True,
    help='debug mode: run in foreground (repeat for more verbosity)')
@click.option('--single-thread', '-S', is_flag=True,
    help='run single-threaded')
@click.option('--container', '-c', 'mount_containers', metavar='CONTAINER', multiple=True,
    help='Container to mount (can be repeated)')
@click.option('--skip-default-containers', '-s', is_flag=True,
    help='skip mounting default-containers from config')
@click.option('--skip-forest-mount', is_flag=True,
    help='skip mounting forest of default user')
@click.option('--default-user', help="specify a default user to be used")
@click.pass_obj
def start(obj: ContextObj, remount, debug, mount_containers, single_thread,
          skip_default_containers, skip_forest_mount, default_user):
    """
    Mount the Wildland filesystem. The default path is ``~/wildland/``, but
    it can be customized in the configuration file
    (``~/.wildland/config.yaml``) as ``mount_dir``.
    """

    if not os.path.exists(obj.mount_dir):
        print(f'Creating: {obj.mount_dir}')
        os.makedirs(obj.mount_dir)

    if obj.fs_client.is_mounted():
        if remount:
            obj.fs_client.unmount()
        else:
            raise CliError('Already mounted')

    if not default_user:
        # Attempt to get '@default' user
        default_user = obj.client.config.get('@default')

    if not default_user:
        raise CliError('No default user available: use --default-user or set '
                       'default user in Wildland config.yaml.')

    try:
        user = obj.client.load_object_from_name(WildlandObject.Type.USER, default_user)
    except (FileNotFoundError, ManifestError) as e:
        raise CliError(f'User {default_user} not found') from e

    to_mount = []
    if mount_containers:
        to_mount += mount_containers

    if not skip_default_containers:
        to_mount += obj.client.config.get('default-containers')

    if not skip_forest_mount:
        forest_containers = [f'{user.owner}:*:']
        to_mount += forest_containers

    if not debug:
        obj.fs_client.mount(single_thread=single_thread, default_user=user)
        _do_mount_containers(obj, to_mount)
        return

    print(f'Mounting in foreground: {obj.mount_dir}')
    print('Press Ctrl-C to unmount')

    p = obj.fs_client.mount(foreground=True, debug=(debug > 1), single_thread=single_thread)
    _do_mount_containers(obj, to_mount)
    try:
        p.wait()
    except KeyboardInterrupt:
        obj.fs_client.unmount()
        p.wait()

    if p.returncode != 0:
        raise CliError('FUSE driver exited with failure')


@main.command(short_help='display mounted containers')
@click.option('--with-subcontainers/--without-subcontainers', '-w/-W', is_flag=True, default=False,
              help='list subcontainers hidden by default')
@click.option('--with-pseudomanifests/--without-pseudomanifests', '-p/-P', is_flag=True,
              default=False, help='list containers with pseudomanifests')
@click.pass_obj
def status(obj: ContextObj, with_subcontainers: bool, with_pseudomanifests: bool):
    """
    Display all mounted containers.
    """
    obj.fs_client.ensure_mounted()

    click.echo('Mounted containers:')
    click.echo()

    storages = list(obj.fs_client.get_info().values())
    for storage in storages:
        if storage['subcontainer_of'] and not with_subcontainers:
            continue
        if storage['hidden'] and not with_pseudomanifests:
            continue
        main_path = storage['paths'][0]
        click.echo(main_path)
        click.echo(f'  storage: {storage["type"]}')
        click.echo('  paths:')
        for path in storage['paths']:
            click.echo(f'    {path}')
        if storage['subcontainer_of']:
            click.echo(f'  subcontainer-of: {storage["subcontainer_of"]}')
        click.echo()

@main.command(short_help='renamed to "start"')
def mount():
    """
    Renamed to "start" command.
    """
    raise CliError('The "wl mount" command has been renamed to "wl start"')


@main.command(short_help='unmount Wildland filesystem', alias=['umount', 'unmount'])
@click.pass_obj
def stop(obj: ContextObj):
    """
    Unmount the Wildland filesystem.
    """

    click.echo(f'Unmounting: {obj.mount_dir}')
    try:
        obj.fs_client.unmount()
    except WildlandError as ex:
        raise CliError(str(ex)) from ex


@main.command(short_help='watch for changes')
@click.option('--with-initial', is_flag=True, help='include initial files')
@click.argument('patterns', metavar='PATH',
                nargs=-1, required=True)
@click.pass_obj
def watch(obj: ContextObj, patterns, with_initial):
    """
    Watch for changes in inside mounted Wildland filesystem.
    """

    obj.fs_client.ensure_mounted()

    for events in obj.fs_client.watch(patterns, with_initial):
        for event in events:
            print(f'{event.event_type}: {event.path}')


if __name__ == '__main__':
    main()  # pylint: disable=no-value-for-parameter
