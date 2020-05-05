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
Common commands (sign, edit, ...) for multiple object types
'''

import sys

import click

from .cli_base import ContextObj, CliError
from ..manifest.manifest import (
    HEADER_SEPARATOR,
    Manifest,
    ManifestError,
    split_header,
)

@click.command(short_help='manifest signing tool')
@click.option('-o', 'output_file', metavar='FILE',
    help='output file (default is stdout)')
@click.option('-i', 'in_place', is_flag=True,
    help='modify the file in place')
@click.argument('input_file', metavar='FILE', required=False)
@click.pass_context
def sign(ctx, input_file, output_file, in_place):
    '''
    Sign a manifest given by FILE, or stdin if not given. The input file can be
    a manifest with or without header. The existing header will be ignored.

    If invoked with manifest type (``user sign``, etc.), the will also validate
    the manifest against schema.
    '''
    obj: ContextObj = ctx.obj

    manifest_type = ctx.parent.command.name
    if manifest_type == 'main':
        manifest_type = None


    if in_place:
        if not input_file:
            raise click.ClickException('Cannot -i without a file')
        if output_file:
            raise click.ClickException('Cannot use both -i and -o')

    obj.loader.load_users()
    data, path = obj.read_manifest_file(input_file, manifest_type)
    if not path:
        raise CliError(f'Manifest not found: {input_file}')

    manifest = Manifest.from_unsigned_bytes(data)
    if manifest_type:
        obj.loader.validate_manifest(manifest, manifest_type)
    manifest.sign(obj.loader.sig, attach_pubkey=(manifest_type == 'user'))
    signed_data = manifest.to_bytes()

    if in_place:
        print(f'Saving: {path}')
        with open(path, 'wb') as f:
            f.write(signed_data)
    elif output_file:
        print(f'Saving: {output_file}')
        with open(output_file, 'wb') as f:
            f.write(signed_data)
    else:
        sys.stdout.buffer.write(signed_data)

@click.command(short_help='verify manifest signature')
@click.argument('input_file', metavar='FILE', required=False)
@click.pass_context
def verify(ctx, input_file):
    '''
    Verify a manifest signature given by FILE, or stdin if not given.

    If invoked with manifests type (``user verify``, etc.), the command will
    also validate the manifest against schema.
    '''
    obj: ContextObj = ctx.obj

    manifest_type = ctx.parent.command.name
    if manifest_type == 'main':
        manifest_type = None

    obj.loader.load_users()
    data, _path = obj.read_manifest_file(input_file, manifest_type)
    try:
        manifest = Manifest.from_bytes(data, obj.loader.sig,
                                       self_signed=(manifest_type == 'user'))
        if manifest_type:
            obj.loader.validate_manifest(manifest, manifest_type)
    except ManifestError as e:
        raise click.ClickException(f'Error verifying manifest: {e}')
    click.echo('Manifest is valid')


@click.command(short_help='edit manifest in external tool')
@click.option('--editor', metavar='EDITOR',
    help='custom editor')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def edit(ctx, editor, input_file):
    '''
    Edit and sign a manifest in a safe way. The command will launch an editor
    and validate the edited file before signing and replacing it.

    If invoked with manifests type (``user edit``, etc.), the command will
    also validate the manifest against schema.
    '''
    obj: ContextObj = ctx.obj

    manifest_type = ctx.parent.command.name
    if manifest_type == 'main':
        manifest_type = None

    data, path = obj.read_manifest_file(input_file, manifest_type)
    if not path:
        raise CliError(f'Manifest not found: {input_file}')

    if HEADER_SEPARATOR in data:
        _, data = split_header(data)

    edited_s = click.edit(data.decode(), editor=editor, extension='.yaml',
                          require_save=False)
    data = edited_s.encode()

    obj.loader.load_users()
    manifest = Manifest.from_unsigned_bytes(data)
    if manifest_type is not None:
        obj.loader.validate_manifest(manifest, manifest_type)
    manifest.sign(obj.loader.sig, attach_pubkey=(manifest_type == 'user'))
    signed_data = manifest.to_bytes()
    with open(path, 'wb') as f:
        f.write(signed_data)
    click.echo(f'Saved: {path}')
