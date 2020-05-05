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

import copy
import json
from pathlib import PurePosixPath

import click

from .base import ContextObj
from .common import sign, verify, edit
from ..container import Container
from ..manifest.manifest import Manifest


def find_by_manifest(container_name):
    '''
    Find container ID by reading the manifest and matching paths.
    '''
    obj: ContextObj = click.get_current_context().obj
    path, manifest = obj.loader.load_manifest(container_name, 'container')
    if not manifest:
        raise click.ClickException(f'Not found: {container_name}')
    click.echo(f'Using manifest: {path}')
    container = Container(manifest)
    mount_path = obj.get_user_path(container.signer, container.paths[0])
    return find_by_path(mount_path)


def find_by_path(mount_path: PurePosixPath):
    '''
    Find container ID by one of mount paths.
    '''
    obj: ContextObj = click.get_current_context().obj
    paths = json.loads(obj.read_control('paths'))
    if str(mount_path) not in paths:
        raise click.ClickException(f'No container found under {mount_path}')
    return paths[str(mount_path)]


@click.group('container', short_help='container management')
def container_():
    '''
    Manage containers
    '''


@container_.command(short_help='create container')
@click.option('--user',
    help='user for signing')
@click.option('--path', multiple=True, required=True,
    help='mount path (can be repeated)')
@click.argument('name', metavar='CONTAINER', required=False)
@click.pass_obj
def create(obj: ContextObj, user, path, name):
    '''
    Create a new container manifest.
    '''

    obj.loader.load_users()
    user = obj.find_user(user)
    path = obj.loader.create_container(user.signer, path, name)
    click.echo(f'Created: {path}')


@container_.command(short_help='update container')
@click.option('--storage', multiple=True,
    help='storage to use (can be repeated)')
@click.argument('cont', metavar='CONTAINER')
@click.pass_obj
def update(obj: ContextObj, storage, cont):
    '''
    Update a container manifest.
    '''

    obj.loader.load_users()
    path, manifest = obj.loader.load_manifest(cont, 'container')
    if not manifest:
        raise click.ClickException(f'Container not found: {cont}')
    assert path

    if not storage:
        print('No change')
        return

    storages = list(manifest.fields['backends']['storage'])
    for storage_name in storage:
        storage_path = obj.loader.find_manifest(storage_name, 'storage')
        if not storage_path:
            raise click.ClickException(
                f'Storage manifest not found: {storage_name}')
        print(f'Adding storage: {storage_path}')
        if str(storage_path) in storages:
            raise click.ClickException('Storage already attached to container')
        storages.append(str(storage_path))

    fields = copy.deepcopy(manifest.fields)
    fields['backends']['storage'] = storages
    new_manifest = Manifest.from_fields(fields)
    obj.loader.validate_manifest(new_manifest, 'container')
    new_manifest.sign(obj.loader.sig)
    signed_data = new_manifest.to_bytes()

    print(f'Saving: {path}')
    with open(path, 'wb') as f:
        f.write(signed_data)


@container_.command('list', short_help='list containers')
@click.pass_obj
def list_(obj: ContextObj):
    '''
    Display known containers.
    '''

    obj.loader.load_users()
    for path, manifest in obj.loader.load_manifests('container'):
        click.echo(path)
        for container_path in manifest.fields['paths']:
            click.echo(f'  path: {container_path}')
        for storage_path in manifest.fields['backends']['storage']:
            click.echo(f'  storage: {storage_path}')


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
    obj.ensure_mounted()
    obj.loader.load_users()

    path, manifest = obj.loader.load_manifest(cont, 'container')
    if not manifest:
        raise click.ClickException(f'Not found: {cont}')

    cont = Container(manifest)
    command = obj.get_command_for_mount_container(cont)

    click.echo(f'Mounting: {path}')
    obj.write_control('mount', json.dumps(command).encode())


@container_.command(short_help='unmount container')
@click.option('--path', metavar='PATH',
    help='mount path to search for')
@click.argument('cont', metavar='CONTAINER', required=False)
@click.pass_obj
def unmount(obj, path, cont):
    '''
    Unmount a container_ You can either specify the container manifest, or
    identify the container by one of its path (using ``--path``).
    '''

    obj.ensure_mounted()
    obj.loader.load_users()

    if bool(cont) + bool(path) != 1:
        raise click.UsageError('Specify either container or --path')

    if cont:
        num = find_by_manifest(cont)
    else:
        num = find_by_path(path)

    click.echo(f'Unmounting storage {num}')
    obj.write_control('unmount', str(num).encode())
