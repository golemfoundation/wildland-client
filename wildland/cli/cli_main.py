# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
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
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Wildland command-line interface.
"""

import os
import logging
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Optional, Sequence, Union

import click

from wildland.control_client import ControlClientError
from wildland.exc import WildlandError
from wildland.manifest.template import TemplateManager
from wildland.wildland_object.wildland_object import WildlandObject
from .cli_base import (
    aliased_group,
    ContextObj,
)
from .cli_exc import CliError
from . import (
    cli_common,
    cli_user,
    cli_forest,
    cli_storage,
    cli_template,
    cli_container,
    cli_bridge,
    cli_transfer,
)

from ..log import init_logging
from ..manifest.manifest import ManifestError
from ..client import Client
from .cli_common import wl_version
from ..debug import start_debugpy_server_if_enabled


logger = logging.getLogger('cli')


PROJECT_PATH = Path(__file__).resolve().parents[1]
FUSE_ENTRY_POINT = PROJECT_PATH / 'wildland-fuse'


@aliased_group('wl', invoke_without_command=True)
@click.option('--dummy/--no-dummy', default=False,
              help='use dummy signatures')
@click.option('--base-dir', default=None,
              help='base directory for configuration')
@click.option('--debug/--no-debug', default=False,
              help='print full traceback on exception')
@click.option('--verbose', '-v', count=True,
              help='output logs (repeat for more verbosity)')
@click.option('--version', is_flag=True, help='output Wildland version')
@click.pass_context
def main(ctx: click.Context, base_dir, dummy, debug, verbose, version):
    # pylint: disable=missing-docstring, unused-argument
    start_debugpy_server_if_enabled()
    if not ctx.invoked_subcommand:
        if version:
            print(wl_version())
            return
        click.echo(ctx.get_help())
        return
    if verbose > 0:
        init_logging(level='DEBUG' if verbose > 1 else 'INFO')
    else:
        init_logging(level='WARNING')
    client = Client(dummy=dummy, base_dir=base_dir)
    ctx.obj = ContextObj(client)


main.add_command(cli_user.user_)
main.add_command(cli_forest.forest_)
main.add_command(cli_storage.storage_)
main.add_command(cli_template.template)
main.add_command(cli_container.container_)
main.add_command(cli_bridge.bridge_)
main.add_alias(**{'users': 'user',
                  'u': 'user',
                  'storages': 'storage',
                  's': 'storage',
                  'containers': 'container',
                  'c': 'container',
                  'storage-template': 'template',
                  't': 'template',
                  'bridges': 'bridge',
                  'b': 'bridge'})

main.add_command(cli_common.version)
main.add_command(cli_common.sign)
main.add_command(cli_common.verify)
main.add_command(cli_common.edit)
main.add_command(cli_common.dump)
main.add_command(cli_common.publish)
main.add_command(cli_common.unpublish)

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
        reordered, err = obj.client.ensure_mount_reference_container(containers)
        if err:
            failed.append(err)

        for container in reordered:
            user_paths = obj.client.get_bridge_paths_for_user(container.owner)
            try:
                commands.extend(cli_container.prepare_mount(
                    obj, container, str(container.local_path), user_paths,
                    remount=False, with_subcontainers=True, subcontainer_of=None, verbose=False,
                    only_subcontainers=False))
            except WildlandError as we:
                failed.append(
                    f'Container {container} (expanded from {name}) cannot be mounted: {we}')
                continue

    click.echo(f'Mounting {len(commands)} containers.')

    try:
        fs_client.mount_multiple_containers(commands)
    except WildlandError as e:
        failed.append(f'Failed to mount: {e}')

    if failed:
        logger.warning('Non-critical error(s) occurred: %s', "\n".join(failed))


@main.command(short_help='mount Wildland filesystem')
@click.option('--remount', '-r', is_flag=True,
    help='if mounted already, remount')
@click.option('--debug', '-d', is_flag=True,
    help='debug mode: run in foreground')
@click.option('--container', '-c', 'mount_containers', metavar='CONTAINER', multiple=True,
    help='container to mount (can be repeated)')
@click.option('--single-thread', '-S', is_flag=True,
    help='run single-threaded')
@click.option('--skip-default-containers', '-s', is_flag=True,
    help='skip mounting default-containers from config')
@click.option('--skip-forest-mount', is_flag=True,
    help='skip mounting forest of default user')
@click.option('--default-user', help='specify a default user to be used')
@click.pass_obj
def start(obj: ContextObj, remount: bool, debug: bool, mount_containers: Sequence[str],
          single_thread: bool, skip_default_containers: bool, skip_forest_mount: bool,
          default_user: Optional[str]):
    """
    Mount the Wildland filesystem. The default path is ``~/wildland/``, but
    it can be customized in the configuration file
    (``~/.wildland/config.yaml``) as ``mount_dir``.
    """

    if not os.path.exists(obj.mount_dir):
        print(f'Creating: {obj.mount_dir}')
        os.makedirs(obj.mount_dir)

    click.echo(f'Starting Wildland at: {obj.mount_dir}')

    if obj.fs_client.is_running():
        if remount:
            obj.fs_client.stop()
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

    to_mount: List[str] = []
    if mount_containers:
        to_mount += mount_containers

    if not skip_default_containers:
        to_mount += obj.client.config.get('default-containers')

    if not skip_forest_mount:
        forest_containers = [f'{user.owner}:*:']
        to_mount += forest_containers

    if not debug:
        obj.fs_client.start(single_thread=single_thread, default_user=user)
        _do_mount_containers(obj, to_mount)
        return

    print(f'Mounting in foreground: {obj.mount_dir}')
    print('Press Ctrl-C to unmount')

    p = obj.fs_client.start(foreground=True, debug=debug, single_thread=single_thread)
    _do_mount_containers(obj, to_mount)
    try:
        p.wait()
    except KeyboardInterrupt:
        obj.fs_client.stop()
        p.wait()

    if p.returncode != 0:
        raise CliError('FUSE driver exited with failure')


@main.command(short_help='display mounted containers and sync jobs')
@click.option('--with-subcontainers/--without-subcontainers', '-w/-W', is_flag=True, default=False,
              help='list subcontainers hidden by default')
@click.option('--with-pseudomanifests/--without-pseudomanifests', '-p/-P', is_flag=True,
              default=False, help='list containers with pseudomanifests')
@click.option('--all-paths', '-a', is_flag=True, default=False,
              help='print all mountpoint paths, including synthetic ones')
@click.pass_obj
def status(obj: ContextObj, with_subcontainers: bool, with_pseudomanifests: bool, all_paths: bool):
    """
    Display all mounted containers and sync jobs.
    """
    if not obj.fs_client.is_running():
        click.echo('Wildland is not mounted, use `wl start` to mount it.')
    else:
        click.echo('Mounted containers:')
        click.echo()

        mounted_storages = obj.fs_client.get_info().values()
        for storage in mounted_storages:
            if storage['subcontainer_of'] and not with_subcontainers:
                continue
            if storage['hidden'] and not with_pseudomanifests:
                continue
            main_path = storage['paths'][0]
            click.echo(main_path)
            click.echo(f'  storage: {storage["type"]}')
            _print_container_paths(storage, all_paths)
            if storage['subcontainer_of']:
                click.echo(f'  subcontainer-of: {storage["subcontainer_of"]}')

    click.echo()
    result = obj.client.run_sync_command('status')
    if len(result) == 0:
        click.echo('No sync jobs running')
    else:
        click.echo('Sync jobs:')
        for s in result:
            click.echo(s)


@main.command(short_help='set the specified storage template as default for container '
                         'cache storages')
@click.argument('template_name', metavar='TEMPLATE', required=True)
@click.pass_obj
def set_default_cache(obj: ContextObj, template_name: str):
    """
    Set the specified storage template as default for container cache storages.
    """
    template_manager = TemplateManager(obj.client.dirs[WildlandObject.Type.TEMPLATE])
    if not template_manager.get_file_path(template_name).exists():
        raise WildlandError(f'Template {template_name} does not exist')
    obj.client.config.update_and_save({'default-cache-template': template_name})
    click.echo(f'Set template {template_name} as default for container cache storages')


def _print_container_paths(storage: Dict, all_paths: bool) -> None:
    if all_paths:
        _print_container_all_paths(storage['paths'])
    elif storage['primary'] and storage['type'] != 'static':
        _print_container_shortened_paths(storage['paths'], storage['categories'])
        _print_container_categories(storage['categories'])
        _print_container_title(storage['title'])


def _echo_indented_status_info(info: str, indent_size: int=0) -> None:
    click.echo(' ' * indent_size + info)


def _print_container_all_paths(paths: List[PurePosixPath]) -> None:
    _echo_indented_status_info('all paths:', 2)

    for path in paths:
        _echo_indented_status_info(str(path), 4)


def _print_container_shortened_paths(paths: List[PurePosixPath], categories: List[PurePosixPath]) \
        -> None:
    """
    Prints mount paths with ``/.users/``, ``/.backends/``, ``/.uuid`` and ``/{category}`` paths
    filtered out (where ``{category}`` is any category from ``categories`` list given as a param).
    """
    def _any_in_path(path_str: str, iterable: Iterable[Union[PurePosixPath, str]]):
        return any(path_str.startswith(str(p)) or ':' + str(p) in path_str for p in iterable)

    def _is_relevant_path(path: PurePosixPath):
        path_str = str(path)
        prefixes = ('/.users/', '/.backends/', '/.uuid/')
        return not _any_in_path(path_str, prefixes) and \
               not _any_in_path(path_str, categories)

    relevant_paths = list(filter(_is_relevant_path, paths))
    if relevant_paths:
        _echo_indented_status_info('paths:', 2)
        for path in relevant_paths:
            _echo_indented_status_info(str(path), 4)


def _print_container_categories(categories: List[PurePosixPath]) -> None:
    if categories:
        _echo_indented_status_info('categories:', 2)
        for category in categories:
            _echo_indented_status_info(str(category), 4)


def _print_container_title(title: Optional[str]) -> None:
    if title:
        _echo_indented_status_info('title:', 2)
        _echo_indented_status_info(title, 4)


@main.command(short_help='unmount Wildland filesystem')
@click.option('--keep-sync-daemon', is_flag=True, help='keep sync daemon running')
@click.pass_obj
def stop(obj: ContextObj, keep_sync_daemon: bool) -> None:
    """
    Unmount the Wildland filesystem.
    """

    click.echo(f'Stopping Wildland at: {obj.mount_dir}')
    try:
        obj.fs_client.stop()
    except WildlandError as ex:
        raise CliError(str(ex)) from ex

    if not keep_sync_daemon:
        try:
            obj.client.run_sync_command('shutdown')
        except ControlClientError:
            pass  # we don't expect a response


@main.command(short_help='watch for changes')
@click.option('--with-initial', is_flag=True, help='include initial files')
@click.argument('patterns', metavar='PATH', nargs=-1, required=True)
@click.pass_obj
def watch(obj: ContextObj, patterns, with_initial) -> None:
    """
    Watch for changes in inside mounted Wildland filesystem.
    """

    obj.fs_client.ensure_mounted()

    for events in obj.fs_client.watch(patterns, with_initial):
        for event in events:
            print(f'{event.event_type}: {event.path}')


if __name__ == '__main__':
    main()  # pylint: disable=no-value-for-parameter
