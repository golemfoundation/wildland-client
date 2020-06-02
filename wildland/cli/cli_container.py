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

import click

from .cli_base import AliasedGroup, ContextObj, CliError
from .cli_common import sign, verify, edit
from ..container import Container


@click.group('container', short_help='container management', cls=AliasedGroup)
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
    user = obj.client.load_user_from(user)

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


@container_.command('list', short_help='list containers')
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
container_.add_alias(ls='list')


container_.add_command(sign)
container_.add_command(verify)
container_.add_command(edit)


@container_.command(short_help='mount container')
@click.argument('cont', metavar='CONTAINER')
@click.pass_obj
def mount(obj: ContextObj, cont):
    '''
    Mount a container given by name or path to manifest. The Wildland system has
    to be mounted first, see ``wl mount``.
    '''
    obj.fs_client.ensure_mounted()
    obj.client.recognize_users()

    container = obj.client.load_container_from(cont)

    click.echo(f'Mounting: {container.local_path}')
    is_default_user = container.signer == obj.client.config.get('default_user')
    storage = obj.client.select_storage(container)
    obj.fs_client.mount_container(container, storage, is_default_user)


@container_.command(short_help='unmount container')
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

container_.add_alias(umount='unmount')
