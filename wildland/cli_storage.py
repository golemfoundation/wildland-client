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

import copy

import botocore.credentials
import botocore.session
import click

from .cli_common import sign, verify, edit
from .manifest.manifest import Manifest

@click.group(short_help='storage management')
def storage():
    '''Manage storages for container'''

@storage.group(short_help='create storage')
def create():
    '''
    Create a new storage manifest.

    The storage has to be associated with a specific container.
    '''


def create_command(storage_type):
    '''
    Decorator for 'storage create' command, with common options.
    '''

    options = [
        create.command(storage_type),
        click.option('--container', metavar='CONTAINER',
                     required=True,
                     help='Container this storage is for'),
        click.option('--update-container', '-u', is_flag=True,
                     help='Update the container after creating storage'),
        click.option('--user',
                     help='user for signing'),
        click.argument('name', metavar='NAME', required=False),
    ]

    def decorator(func):
        for option in reversed(options):
            func = option(func)
        return func
    return decorator


def _do_create(ctx, type_, fields, name, user, container, update_container):
    ctx.obj.loader.load_users()
    user = ctx.obj.find_user(user)

    container_path, container_manifest = ctx.obj.loader.load_manifest(
        container, 'container')
    if not container_manifest:
        raise click.ClickException(f'Not found: {container}')
    container_mount_path = container_manifest.fields['paths'][0]
    click.echo(f'Using container: {container_path} ({container_mount_path})')
    fields['container_path'] = container_mount_path

    storage_path = ctx.obj.loader.create_storage(
        user.pubkey, type_, fields, name)
    click.echo('Created: {}'.format(storage_path))

    if update_container:
        click.echo('Adding storage to container')
        fields = copy.deepcopy(container_manifest.fields)
        fields['backends']['storage'].append(str(storage_path))
        container_manifest = Manifest.from_fields(fields)
        ctx.obj.loader.validate_manifest(container_manifest, 'container')
        container_manifest.sign(ctx.obj.loader.sig)
        signed_data = container_manifest.to_bytes()
        click.echo(f'Saving: {container_path}')
        with open(container_path, 'wb') as f:
            f.write(signed_data)

@create_command('local')
@click.pass_context
def create_local(ctx, path, **kwds):
    '''Create local storage'''

    fields = {'path': path}
    return _do_create(ctx, ctx.command.name, fields, **kwds)


@create_command('s3')
@click.option('--bucket', metavar='BUCKET', required=True)
@click.pass_context
def create_s3(ctx, bucket, **kwds):
    '''
    Create S3 storage in BUCKET. The storage will be named NAME.
    '''

    click.echo('Resolving AWS credentials...')
    session = botocore.session.Session()
    resolver = botocore.credentials.create_credential_resolver(session)
    credentials = resolver.load_credentials()
    if not credentials:
        raise click.ClickException(
            "AWS not configured, run 'aws configure' first")
    click.echo(f'Credentials found by method: {credentials.method}')

    fields = {
        'bucket': bucket,
        'credentials': {
            'access_key': credentials.access_key,
            'secret_key': credentials.secret_key,
        }
    }
    return _do_create(ctx, ctx.command.name, fields, **kwds)


@storage.command('list', short_help='list storages')
@click.pass_context
def list_(ctx):
    '''
    Display known storages.
    '''

    ctx.obj.loader.load_users()
    for path, manifest in ctx.obj.loader.load_manifests('storage'):
        click.echo(path)
        storage_type = manifest.fields['type']
        click.echo(f'  type: {storage_type}')
        if storage_type == 'local':
            click.echo(f'  path: {manifest.fields["path"]}')


storage.add_command(sign)
storage.add_command(verify)
storage.add_command(edit)
