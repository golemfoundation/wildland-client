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

import click

from . import cli_common
from .container import Container
from .manifest.manifest import Manifest


def find_by_manifest(container_name):
    '''
    Find container ID by reading the manifest and matching paths.
    '''
    ctx = click.get_current_context()
    path, manifest = ctx.obj.loader.load_manifest(container_name, 'container')
    if not manifest:
        raise click.ClickException(f'Not found: {container_name}')
    click.echo(f'Using manifest: {path}')
    mount_path = manifest.fields['paths'][0]
    return find_by_path(mount_path)

def find_by_path(mount_path):
    '''
    Find container ID by one of mount paths.
    '''
    ctx = click.get_current_context()
    paths = json.loads(ctx.obj.read_control('paths'))
    if mount_path not in paths:
        raise click.ClickException(f'No container found under {mount_path}')
    return paths[mount_path]


@click.group('container', short_help='container management')
def container():
    '''
    Manage containers
    '''


@container.command(short_help='create container')
@click.option('--user',
    help='user for signing')
@click.option('--path', multiple=True, required=True,
    help='mount path (can be repeated)')
@click.argument('name', metavar='CONTAINER', required=False)
@click.pass_context
def create(ctx, user, path, name):
    '''
    Create a new container manifest.
    '''

    ctx.obj.loader.load_users()
    user = ctx.obj.find_user(user)
    path = ctx.obj.loader.create_container(user.signer, path, name)
    click.echo(f'Created: {path}')


@container.command(short_help='update container')
@click.option('--storage', multiple=True,
    help='storage to use (can be repeated)')
@click.argument('cont', metavar='CONTAINER')
@click.pass_context
def update(ctx, storage, cont):
    '''
    Update a container manifest.
    '''

    ctx.obj.loader.load_users()
    path, manifest = ctx.obj.loader.load_manifest(cont, 'container')
    if not path:
        raise click.ClickException(f'Container not found: {cont}')

    if not storage:
        print('No change')
        return

    storages = list(manifest.fields['backends']['storage'])
    for storage_name in storage:
        storage_path = ctx.obj.loader.find_manifest(storage_name, 'storage')
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
    ctx.obj.loader.validate_manifest(new_manifest, 'container')
    new_manifest.sign(ctx.obj.loader.sig)
    signed_data = new_manifest.to_bytes()

    print(f'Saving: {path}')
    with open(path, 'wb') as f:
        f.write(signed_data)


@container.command('list', short_help='list containers')
@click.pass_context
def list_(ctx):
    '''
    Display known containers.
    '''

    ctx.obj.loader.load_users()
    for path, manifest in ctx.obj.loader.load_manifests('container'):
        click.echo(path)
        for container_path in manifest.fields['paths']:
            click.echo(f'  path: {container_path}')
        for storage_path in manifest.fields['backends']['storage']:
            click.echo(f'  storage: {storage_path}')


container.add_command(cli_common.sign)
container.add_command(cli_common.verify)
container.add_command(cli_common.edit)


@container.command(short_help='mount container')
@click.argument('cont', metavar='CONTAINER')
@click.pass_context
def mount(ctx, cont):
    '''
    Mount a container given by name or path to manifest. The Wildland system has
    to be mounted first, see ``wl mount``.
    '''
    ctx.obj.ensure_mounted()
    ctx.obj.loader.load_users()

    path, manifest = ctx.obj.loader.load_manifest(cont, 'container')
    if not manifest:
        raise click.ClickException(f'Not found: {cont}')

    cont = Container(manifest)
    command = ctx.obj.get_command_for_mount_container(cont)

    click.echo(f'Mounting: {path}')
    ctx.obj.write_control('mount', json.dumps(command).encode())


@container.command(short_help='unmount container')
@click.option('--path', metavar='PATH',
    help='mount path to search for')
@click.argument('cont', metavar='CONTAINER', required=False)
@click.pass_context
def unmount(ctx, path, cont):
    '''
    Unmount a container. You can either specify the container manifest, or
    identify the container by one of its path (using ``--path``).
    '''

    ctx.obj.ensure_mounted()
    ctx.obj.loader.load_users()

    if bool(cont) + bool(path) != 1:
        raise click.UsageError('Specify either container or --path')

    if cont:
        num = find_by_manifest(cont)
    else:
        num = find_by_path(path)

    click.echo(f'Unmounting storage {num}')
    ctx.obj.write_control('unmount', str(num).encode())
