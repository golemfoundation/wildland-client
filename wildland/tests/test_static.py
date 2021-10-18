# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
#                    Marek Marczykowski-Górecki <marmarek@invisiblethingslab.com>,
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

# pylint: disable=missing-docstring

import os
import uuid

from ..utils import yaml_parser


def storage(content):
    return {
        'type': 'static',
        'owner': '0xaaaa',
        'backend-id': str(uuid.uuid4()),
        'content': content
    }


def test_static_empty(env):
    env.mount_storage(['/static'], storage({}))
    assert sorted(os.listdir(env.mnt_dir / 'static')) == []


def test_static_fuse(env):
    env.mount_storage(['/static'], storage({
        'foo.txt': 'foo data',
        'empty-dir': {},
        'dir': {
            'foo.txt': 'foo2 data',
            'bar.txt': 'bar data',
        },
    }))
    assert sorted(os.listdir(env.mnt_dir / 'static')) == ['dir', 'empty-dir', 'foo.txt']
    assert sorted(os.listdir(env.mnt_dir / 'static/dir')) == ['bar.txt', 'foo.txt']
    assert (env.mnt_dir / 'static/foo.txt').read_text() == 'foo data'
    assert (env.mnt_dir / 'static/dir/bar.txt').read_text() == 'bar data'
    assert (env.mnt_dir / 'static/dir/foo.txt').read_text() == 'foo2 data'


def test_cli(base_dir, cli):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'static', 'Storage',
        '--file', 'foo.txt=foo content',
        '--file', 'bar.txt=bar content',
        '--file', 'foo/bar.txt=foobar content',
        '--container', 'Container', '--no-inline', '--no-encrypt-manifest')
    with open(base_dir / 'storage/Storage.storage.yaml') as f:
        data = f.read()
    manifest = yaml_parser.load(data.split('---')[1])

    assert 'content' in manifest
    assert manifest['content'] == {
        'foo.txt': 'foo content',
        'bar.txt': 'bar content',
        'foo': {'bar.txt': 'foobar content'},
    }
