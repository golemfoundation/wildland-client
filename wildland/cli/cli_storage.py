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
Storage object
'''

from typing import Type
import functools

import click

from .cli_base import AliasedGroup, ContextObj
from .cli_common import sign, verify, edit
from ..storage import Storage

from ..storage_backends.base import StorageBackend
from ..storage_backends.dispatch import get_storage_backends


@click.group('storage', short_help='storage management', cls=AliasedGroup)
def storage_():
    '''Manage storages for container'''

@storage_.group(short_help='create storage')
def create():
    '''
    Create a new storage manifest.

    The storage has to be associated with a specific container.
    '''


def _make_create_command(backend: Type[StorageBackend]):
    params = [
        click.Option(['--container'], metavar='CONTAINER',
                     required=True,
                     help='Container this storage is for'),
        click.Option(['--update-container/--no-update-container', '-u/-n'], default=True,
                     help='Update the container after creating storage'),
        click.Option(['--trusted'], is_flag=True,
                     help='Make the storage trusted'),
        click.Option(['--inline'], is_flag=True,
                     help='Add the storage directly to container '
                     'manifest, instead of saving it to a file'),
        click.Argument(['name'], metavar='NAME', required=False),
    ]

    params.extend(backend.cli_options())

    callback = functools.partial(_do_create, backend=backend)

    command = click.Command(
        name=backend.TYPE,
        help=f'Create {backend.TYPE} storage',
        params=params,
        callback=callback)
    return command


def _add_create_commands(group):
    for backend in get_storage_backends().values():
        command = _make_create_command(backend)
        group.add_command(command)


def _do_create(
        backend: Type[StorageBackend],
        name,
        container,
        update_container,
        trusted,
        inline,
        **data):

    if inline and not update_container:
        raise click.ClickException('The --inline option requires --update-container')

    obj: ContextObj = click.get_current_context().obj

    obj.client.recognize_users()

    container = obj.client.load_container_from(container)
    if not container.local_path:
        raise click.ClickException('Need a local container')

    container_mount_path = container.paths[0]
    click.echo(f'Using container: {container.local_path} ({container_mount_path})')

    params = backend.cli_create(data)

    storage = Storage(
        storage_type=backend.TYPE,
        signer=container.signer,
        container_path=container_mount_path,
        params=params,
        trusted=trusted,
    )
    storage.validate()

    if inline:
        click.echo('Adding storage directly to container')
        container.backends.append(storage.to_unsigned_manifest()._fields)
        click.echo(f'Saving: {container.local_path}')
        obj.client.save_container(container)

    else:
        storage_path = obj.client.save_new_storage(storage, name)
        click.echo('Created: {}'.format(storage_path))

        if update_container:
            click.echo('Adding storage to container')
            container.backends.append(obj.client.local_url(storage_path))
            click.echo(f'Saving: {container.local_path}')
            obj.client.save_container(container)


@storage_.command('list', short_help='list storages')
@click.pass_obj
def list_(obj: ContextObj):
    '''
    Display known storages.
    '''

    obj.client.recognize_users()
    for storage in obj.client.load_storages():
        click.echo(storage.local_path)
        click.echo(f'  type: {storage.storage_type}')
        if storage.storage_type == 'local':
            click.echo(f'  path: {storage.params["path"]}')
storage_.add_alias(ls='list')


storage_.add_command(sign)
storage_.add_command(verify)
storage_.add_command(edit)

_add_create_commands(create)
