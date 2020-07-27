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
Manage containers
'''

from pathlib import PurePosixPath
from typing import List, Tuple

import click

from .cli_base import aliased_group, ContextObj, CliError
from .cli_common import sign, verify, edit
from ..container import Container
from ..storage import Storage


@aliased_group('container', short_help='container management')
def container_():
    '''
    Manage containers
    '''


@container_.command(short_help='create container')
@click.option('--user',
    help='user for signing')
@click.option('--path', multiple=True, required=True,
    help='mount path (can be repeated)')
@click.option('--update-user/--no-update-user', '-u/-n', default=False,
              help='Attach the container to the user')
@click.argument('name', metavar='CONTAINER', required=False)
@click.pass_obj
def create(obj: ContextObj, user, path, name, update_user):
    '''
    Create a new container manifest.
    '''

    obj.client.recognize_users()
    user = obj.client.load_user_from(user or '@default-signer')

    container = Container(
        signer=user.signer,
        paths=[PurePosixPath(p) for p in path],
        backends=[],
    )
    path = obj.client.save_new_container(container, name)
    click.echo(f'Created: {path}')

    if update_user:
        if not user.local_path:
            raise CliError('Cannot update user because the manifest path is unknown')
        click.echo('Attaching container to user')

        user.containers.append(str(obj.client.local_url(path)))
        obj.client.save_user(user)


@container_.command(short_help='update container')
@click.option('--storage', multiple=True,
    help='storage to use (can be repeated)')
@click.argument('cont', metavar='CONTAINER')
@click.pass_obj
def update(obj: ContextObj, storage, cont):
    '''
    Update a container manifest.
    '''

    obj.client.recognize_users()
    container = obj.client.load_container_from(cont)
    if container.local_path is None:
        raise click.ClickException('Can only update a local manifest')

    if not storage:
        print('No change')
        return

    for storage_name in storage:
        storage = obj.client.load_storage_from(storage_name)
        assert storage.local_path
        print(f'Adding storage: {storage.local_path}')
        if str(storage.local_path) in container.backends:
            raise click.ClickException('Storage already attached to container')
        container.backends.append(obj.client.local_url(storage.local_path))

    obj.client.save_container(container)


@container_.command('list', short_help='list containers', alias=['ls'])
@click.pass_obj
def list_(obj: ContextObj):
    '''
    Display known containers.
    '''

    obj.client.recognize_users()
    for container in obj.client.load_containers():
        click.echo(container.local_path)
        click.echo(f'  signer: {container.signer}')
        for container_path in container.paths:
            click.echo(f'  path: {container_path}')
        for storage_path in container.backends:
            click.echo(f'  storage: {storage_path}')
        click.echo()

@container_.command('delete', short_help='delete a container', alias=['rm'])
@click.pass_obj
@click.option('--force', '-f', is_flag=True,
              help='delete even when using local storage manifests')
@click.option('--cascade', is_flag=True,
              help='also delete local storage manifests')
@click.argument('name', metavar='NAME')
def delete(obj: ContextObj, name, force, cascade):
    '''
    Delete a container.
    '''
    # TODO: also consider detecting user-container link (i.e. user's main
    # container).
    obj.client.recognize_users()

    container = obj.client.load_container_from(name)
    if not container.local_path:
        raise CliError('Can only delete a local manifest')

    has_local = False
    for url_or_dict in list(container.backends):
        if isinstance(url_or_dict, str):
            path = obj.client.parse_file_url(url_or_dict, container.signer)
            if path and path.exists():
                if cascade:
                    click.echo('Deleting storage: {}'.format(path))
                    path.unlink()
                else:
                    click.echo('Container refers to a local manifest: {}'.format(path))
                    has_local = True

    if has_local and not force:
        raise CliError('Container refers to local manifests, not deleting '
                       '(use --force or --cascade)')

    click.echo(f'Deleting: {container.local_path}')
    container.local_path.unlink()


container_.add_command(sign)
container_.add_command(verify)
container_.add_command(edit)


@container_.command(short_help='mount container')
@click.option('--remount/--no-remount', '-r/-n', default=True,
              help='Remount existing container, if found')
@click.option('--save', '-s', is_flag=True,
              help='Save the container to be mounted at startup')
@click.argument('container_names', metavar='CONTAINER', nargs=-1, required=True)
@click.pass_obj
def mount(obj: ContextObj, container_names, remount, save):
    '''
    Mount a container given by name or path to manifest. Repeat the argument to
    mount multiple containers.

    The Wildland system has to be mounted first, see ``wl mount``.
    '''
    obj.fs_client.ensure_mounted()
    obj.client.recognize_users()

    containers = []
    for container_name in container_names:
        for container in obj.client.load_containers_from(container_name):
            click.echo(f'Loaded: {container.local_path}')
            containers.append(container)

            if not remount and obj.fs_client.find_storage_id(container) is not None:
                raise CliError('Already mounted: {container.local_path}')

    click.echo('Determining storage')

    params: List[Tuple[Container, Storage, bool]] = []
    for container in containers:
        is_default_user = container.signer == obj.client.config.get('@default')
        storage = obj.client.select_storage(container)
        params.append((container, storage, is_default_user))

    if len(params) > 0:
        click.echo(f'Mounting {len(params)} containers')
    else:
        click.echo('Mounting container')
    obj.fs_client.mount_multiple_containers(params, remount=remount)

    if save:
        default_containers = obj.client.config.get('default-containers')
        default_containers_set = set(default_containers)
        new_default_containers = default_containers.copy()
        for container_name in container_names:
            if container_name in default_containers_set:
                click.echo(f'Already in default-containers: {container_name}')
                continue
            click.echo(f'Adding to default-containers: {container_name}')
            default_containers_set.add(container_name)
            new_default_containers.append(container_name)
        if len(new_default_containers) > len(default_containers):
            obj.client.config.update_and_save(
                {'default-containers': new_default_containers})


@container_.command(short_help='unmount container', alias=['umount'])
@click.option('--path', metavar='PATH',
    help='mount path to search for')
@click.argument('cont', metavar='CONTAINER', required=False)
@click.pass_obj
def unmount(obj: ContextObj, path: str, cont):
    '''
    Unmount a container_ You can either specify the container manifest, or
    identify the container by one of its path (using ``--path``).
    '''

    obj.fs_client.ensure_mounted()
    obj.client.recognize_users()

    if bool(cont) + bool(path) != 1:
        raise click.UsageError('Specify either container or --path')

    if cont:
        container = obj.client.load_container_from(cont)
        storage_id = obj.fs_client.find_storage_id(container)
    else:
        storage_id = obj.fs_client.find_storage_id_by_path(PurePosixPath(path))

    if storage_id is None:
        raise click.ClickException('Container not mounted')

    click.echo(f'Unmounting storage {storage_id}')
    obj.fs_client.unmount_container(storage_id)
