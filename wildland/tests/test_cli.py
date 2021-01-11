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

# pylint: disable=missing-docstring,redefined-outer-name,too-many-lines

import shutil
import subprocess
import time
import os

import pytest
import yaml

from ..manifest.manifest import ManifestError
from ..cli.cli_base import CliError


def modify_file(path, pattern, replacement):
    with open(path) as f:
        data = f.read()
    assert pattern in data
    data = data.replace(pattern, replacement)
    with open(path, 'w') as f:
        f.write(data)


@pytest.fixture
def cleanup():
    cleanup_functions = []

    def add_cleanup(func):
        cleanup_functions.append(func)

    yield add_cleanup

    for f in cleanup_functions:
        f()


## Users

def test_user_create(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    with open(base_dir / 'users/User.user.yaml') as f:
        data = f.read()

    assert "owner: '0xaaa'" in data

    with open(base_dir / 'config.yaml') as f:
        config = f.read()
    assert "'@default': '0xaaa'" in config
    assert "'@default-owner': '0xaaa'" in config


def test_user_create_additional_keys(cli, base_dir):
    cli('user', 'create', 'User', '--add-pubkey', 'key.0xbbb')
    with open(base_dir / 'users/User.user.yaml') as f:
        data = f.read()

    assert 'pubkeys:\n- key.0x111\n- key.0xbbb' in data


def test_user_list(cli, base_dir):
    cli('user', 'create', 'User1', '--key', '0xaaa',
        '--path', '/users/Foo', '--path', '/users/Bar')
    cli('user', 'create', 'User2', '--key', '0xbbb')
    result = cli('user', 'list', capture=True)
    assert result.splitlines() == [
        str(base_dir / 'users/User1.user.yaml') + ' (@default) (@default-owner)',
        '  owner: 0xaaa',
        '  private and public keys available',
        '   path: /users/Foo',
        '   path: /users/Bar',
        '',
        str(base_dir / 'users/User2.user.yaml'),
        '  owner: 0xbbb',
        '  private and public keys available',
        '   path: /users/User2',
        ''
    ]


def test_user_delete(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')

    user_path = base_dir / 'users/User.user.yaml'
    assert user_path.exists()
    container_path = base_dir / 'containers/Container.container.yaml'
    assert container_path.exists()

    with pytest.raises(CliError, match='User still has manifests'):
        cli('user', 'delete', 'User')

    cli('user', 'delete', '--force', 'User')
    assert not user_path.exists()
    assert container_path.exists()


def test_user_delete_cascade(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'local', 'Storage', '--path', '/PATH',
        '--container', 'Container')

    user_path = base_dir / 'users/User.user.yaml'
    assert user_path.exists()
    container_path = base_dir / 'containers/Container.container.yaml'
    assert container_path.exists()

    cli('user', 'delete', '--cascade', 'User')
    assert not user_path.exists()
    assert not container_path.exists()


def test_user_verify(cli):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('user', 'verify', 'User')


def test_user_verify_bad_sig(cli, cli_fail, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    modify_file(base_dir / 'users/User.user.yaml', 'dummy.0xaaa', 'dummy.0xbbb')
    cli_fail('user', 'verify', 'User')


def test_user_verify_bad_fields(cli, cli_fail, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    modify_file(base_dir / 'users/User.user.yaml', 'owner:', 'extra: xxx\nowner:')
    cli_fail('user', 'verify', 'User')


def test_user_sign(cli, cli_fail, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    tmp_file = base_dir / 'tmp.yaml'
    shutil.copyfile(base_dir / 'users/User.user.yaml', tmp_file)

    modify_file(tmp_file, 'dummy.0xaaa', 'outdated.0xaaa')
    cli_fail('user', 'verify', tmp_file)

    cli('user', 'sign', '-i', tmp_file)
    cli('user', 'verify', tmp_file)


def test_user_edit(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    editor = r'sed -i s,\'0xaaa\',\"0xaaa\",g'
    cli('user', 'edit', 'User', '--editor', editor)
    with open(base_dir / 'users/User.user.yaml') as f:
        data = f.read()
    assert '"0xaaa"' in data


def test_user_edit_bad_fields(cli, cli_fail):
    cli('user', 'create', 'User', '--key', '0xaaa')
    editor = 'sed -i s,owner,Signer,g'
    cli_fail('user', 'edit', 'User', '--editor', editor)


def test_user_edit_editor_failed(cli, cli_fail):
    cli('user', 'create', 'User', '--key', '0xaaa')
    editor = 'false'
    cli_fail('user', 'edit', 'User', '--editor', editor)


## Storage

def test_storage_create(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'local', 'Storage', '--path', '/PATH',
        '--container', 'Container', '--no-update-container', '--no-inline')
    with open(base_dir / 'storage/Storage.storage.yaml') as f:
        data = f.read()

    assert "owner: '0xaaa'" in data
    assert "path: /PATH" in data


def test_storage_create_not_inline(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'local', 'Storage', '--path', '/PATH',
        '--container', 'Container', '--no-inline')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        data = f.read()

    storage_path = base_dir / 'storage/Storage.storage.yaml'
    assert str(storage_path) in data


def test_storage_create_inline(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'local', 'Storage', '--path', '/STORAGE',
        '--container', 'Container', '--inline')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        data = f.read()

    assert '/STORAGE' in data


def test_storage_delete(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'local', 'Storage', '--path', '/PATH',
        '--container', 'Container', '--no-inline')

    storage_path = base_dir / 'storage/Storage.storage.yaml'
    assert storage_path.exists()

    with pytest.raises(CliError, match='Storage is still used'):
        cli('storage', 'delete', 'Storage')

    cli('storage', 'delete', '--force', 'Storage')
    assert not storage_path.exists()


def test_storage_delete_cascade(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'local', 'Storage', '--path', '/PATH',
        '--container', 'Container', '--no-inline')

    storage_path = base_dir / 'storage/Storage.storage.yaml'
    assert storage_path.exists()
    container_path = base_dir / 'containers/Container.container.yaml'
    assert str(storage_path) in container_path.read_text()

    cli('storage', 'delete', '--cascade', 'Storage')
    assert not storage_path.exists()
    assert str(storage_path) not in container_path.read_text()


def test_storage_list(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'local', 'Storage', '--path', '/PATH',
        '--container', 'Container', '--no-inline')

    result = cli('storage', 'list', capture=True)
    assert result.splitlines() == [
        str(base_dir / 'storage/Storage.storage.yaml'),
        '  type: local',
        '  path: /PATH',
    ]


## Container


def test_container_create(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    with open(base_dir / 'containers/Container.container.yaml') as f:
        data = f.read()

    assert "owner: '0xaaa'" in data
    assert "/PATH" in data
    assert "/.uuid/" in data


def test_container_create_update_user(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH', '--update-user')

    with open(base_dir / 'users/User.user.yaml') as f:
        data = f.read()

    assert 'containers/Container.container.yaml' in data


def test_container_update(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')

    cli('storage', 'create', 'local', 'Storage', '--path', '/PATH',
        '--container', 'Container', '--no-update-container', '--no-inline')
    cli('container', 'update', 'Container', '--storage', 'Storage')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        data = f.read()

    storage_path = base_dir / 'storage/Storage.storage.yaml'
    assert str(storage_path) in data


def test_container_publish(cli, tmp_path):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'local', 'Storage', '--path', os.fspath(tmp_path),
        '--container', 'Container', '--inline')

    cli('container', 'publish', 'Container', '0xaaa:/PATH:/published.yaml')

    assert (tmp_path / 'published.yaml').exists()


def test_container_delete(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')

    cli('storage', 'create', 'local', 'Storage', '--path', '/PATH',
        '--container', 'Container', '--no-inline')

    container_path = base_dir / 'containers/Container.container.yaml'
    assert container_path.exists()
    storage_path = base_dir / 'storage/Storage.storage.yaml'
    assert storage_path.exists()

    with pytest.raises(CliError, match='Container refers to local manifests'):
        cli('container', 'delete', 'Container')

    # Should not complain if the storage manifest does not exist
    storage_path.unlink()
    cli('container', 'delete', 'Container')
    assert not container_path.exists()


def test_container_delete_force(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')

    cli('storage', 'create', 'local', 'Storage', '--path', '/PATH',
        '--container', 'Container', '--no-inline')

    container_path = base_dir / 'containers/Container.container.yaml'
    assert container_path.exists()
    storage_path = base_dir / 'storage/Storage.storage.yaml'
    assert storage_path.exists()

    cli('container', 'delete', '--force', 'Container')
    assert not container_path.exists()
    assert storage_path.exists()


def test_container_delete_cascade(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')

    cli('storage', 'create', 'local', 'Storage', '--path', '/PATH',
        '--container', 'Container', '--no-inline')

    container_path = base_dir / 'containers/Container.container.yaml'
    assert container_path.exists()
    storage_path = base_dir / 'storage/Storage.storage.yaml'
    assert storage_path.exists()

    cli('container', 'delete', '--cascade', 'Container')
    assert not container_path.exists()
    assert not storage_path.exists()


def test_container_delete_umount(cli, base_dir, control_client):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'local', 'Storage', '--path', '/PATH',
        '--container', 'Container', '--no-inline')

    control_client.expect('paths', {})
    control_client.expect('mount')

    cli('container', 'mount', 'Container')

    (base_dir / 'storage/Storage.storage.yaml').unlink()

    with open(base_dir / 'containers/Container.container.yaml') as f:
        documents = list(yaml.safe_load_all(f))
    path = documents[1]['paths'][0]
    control_client.expect('unmount')
    control_client.expect('paths', {
        f'/.users/0xaaa{path}': [101],
        path: [102],
        '/PATH2': [103],
    })

    cli('container', 'delete', 'Container')

    container_path = base_dir / 'containers/Container.container.yaml'
    assert not container_path.exists()


def test_container_list(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')

    result = cli('container', 'list', capture=True)
    out_lines = result.splitlines()
    assert str(base_dir / 'containers/Container.container.yaml') in out_lines
    assert '  path: /PATH' in out_lines


def test_container_mount(cli, base_dir, control_client):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'local', 'Storage', '--path', '/PATH',
        '--container', 'Container')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        documents = list(yaml.safe_load_all(f))
    path = documents[1]['paths'][0]

    control_client.expect('paths', {})
    control_client.expect('mount')

    cli('container', 'mount', 'Container')

    command = control_client.calls['mount']['items']
    assert command[0]['storage']['owner'] == '0xaaa'
    assert command[0]['paths'] == [
        f'/.users/0xaaa{path}',
        '/.users/0xaaa/PATH',
        path,
        '/PATH',
    ]

    modify_file(base_dir / 'config.yaml', "'@default': '0xaaa'", '')

    # The command should not contain the default path.
    cli('container', 'mount', 'Container')

    command = control_client.calls['mount']['items']
    assert command[0]['storage']['owner'] == '0xaaa'
    assert command[0]['paths'] == [
        f'/.users/0xaaa{path}',
        '/.users/0xaaa/PATH',
    ]
    assert command[0]['extra']['trusted_owner'] is None


def test_container_mount_store_trusted_owner(cli, control_client):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'local', 'Storage', '--path', '/PATH',
        '--container', 'Container', '--trusted')

    control_client.expect('paths', {})
    control_client.expect('mount')

    cli('container', 'mount', 'Container')

    command = control_client.calls['mount']['items']
    assert command[0]['extra']['trusted_owner'] == '0xaaa'


def test_container_mount_glob(cli, base_dir, control_client):
    # The glob pattern will be normally expanded by shell,
    # but this feature is also used with default_containers.

    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container1', '--path', '/PATH1')
    cli('container', 'create', 'Container2', '--path', '/PATH2')
    cli('storage', 'create', 'local', 'Storage', '--path', '/PATH',
        '--container', 'Container1')
    cli('storage', 'create', 'local', 'Storage', '--path', '/PATH',
        '--container', 'Container2')

    control_client.expect('paths', {})
    control_client.expect('mount')

    cli('container', 'mount', base_dir / 'containers' / '*.yaml')

    command = control_client.calls['mount']['items']
    assert len(command) == 2
    assert command[0]['paths'][1] == '/.users/0xaaa/PATH1'
    assert command[1]['paths'][1] == '/.users/0xaaa/PATH2'


def test_container_mount_save(cli, base_dir, control_client):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'local', 'Storage', '--path', '/PATH',
        '--container', 'Container')

    control_client.expect('paths', {})
    control_client.expect('mount')

    cli('container', 'mount', '--save', 'Container')

    with open(base_dir / 'config.yaml') as f:
        config = yaml.load(f)
    assert config['default-containers'] == ['Container']

    # Will not add the same container twice
    cli('container', 'mount', '--save', 'Container')

    with open(base_dir / 'config.yaml') as f:
        config = yaml.load(f)
    assert config['default-containers'] == ['Container']


def test_container_mount_inline_storage(cli, base_dir, control_client):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'local', 'Storage', '--path', '/STORAGE',
        '--container', 'Container', '--inline')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        documents = list(yaml.safe_load_all(f))
    path = documents[1]['paths'][0]

    control_client.expect('paths', {})
    control_client.expect('mount')

    cli('container', 'mount', 'Container')

    command = control_client.calls['mount']['items']
    assert command[0]['storage']['owner'] == '0xaaa'
    assert command[0]['storage']['path'] == '/STORAGE'
    assert command[0]['paths'] == [
        f'/.users/0xaaa{path}',
        '/.users/0xaaa/PATH',
        path,
        '/PATH',
    ]


def test_container_mount_check_trusted_owner(cli, base_dir, control_client):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'local', 'Storage', '--path', '/PATH',
        '--container', 'Container')

    manifest_path = base_dir / 'mnt/trusted/Container.container.yaml'

    # Write an unsigned container manifest to mnt/trusted/

    content = (base_dir / 'containers/Container.container.yaml').read_text()
    content = content[content.index('---'):]
    os.mkdir(base_dir / 'mnt/trusted')
    with open(manifest_path, 'w') as f:
        f.write(content)

    # Prepare data in .control

    def make_info(trusted_owner):
        return {
            '1': {
                'paths': ['/PATH'],
                'type': 'local',
                'extra': {'trusted_owner': trusted_owner}
            }
        }

    os.mkdir(base_dir / 'mnt/.control/storage')
    os.mkdir(base_dir / 'mnt/.control/storage/1')
    control_client.expect('paths', {'/trusted': [1]})
    control_client.expect('mount')

    # Should not mount if the storage is not trusted

    control_client.expect('info', make_info(None))
    with pytest.raises(ManifestError, match='Signature expected'):
        cli('container', 'mount', manifest_path)

    # Should not mount if the owner is different

    control_client.expect('info', make_info('0xbbb'))
    with pytest.raises(ManifestError, match='Wrong owner for manifest without signature'):
        cli('container', 'mount', manifest_path)

    # Should mount if the storage is trusted and with right owner

    control_client.expect('info', make_info('0xaaa'))
    cli('container', 'mount', manifest_path)


def test_container_unmount(cli, base_dir, control_client):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        documents = list(yaml.safe_load_all(f))
    path = documents[1]['paths'][0]

    control_client.expect('paths', {
        f'/.users/0xaaa{path}': [101],
        path: [102],
        '/PATH2': [103],
    })
    control_client.expect('unmount')
    cli('container', 'unmount', 'Container')

    assert control_client.calls['unmount']['storage_id'] == 101


def test_container_other_signer(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa', '--add-pubkey', 'key.0xbbb')
    cli('user', 'create', 'User2', '--key', '0xbbb')

    cli('container', 'create', 'Container', '--path', '/PATH', '--user', 'User2')

    modify_file(base_dir / 'containers/Container.container.yaml',
                "owner: '0xbbb'", "owner: '0xaaa'")

    cli('storage', 'create', 'local', 'Storage', '--path', '/PATH',
        '--container', 'Container')


def test_container_unmount_by_path(cli, control_client):
    control_client.expect('paths', {
        '/PATH': [101],
        '/PATH2': [102],
    })
    control_client.expect('unmount')
    cli('container', 'unmount', '--path', '/PATH2')

    assert control_client.calls['unmount']['storage_id'] == 102


def test_container_create_missing_params(cli):
    cli('user', 'create', 'User', '--key', '0xaaa')

    with pytest.raises(CliError, match='--category option requires --title'
                                       ' or container name'):
        cli('container', 'create', '--path', '/PATH',
            '--category', '/c1/c2', '--category', '/c3')


def test_container_extended_paths(cli, control_client, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH', '--title', 'title',
        '--category', '/c1/c2', '--category', '/c3')
    cli('storage', 'create', 'local', 'Storage', '--path', '/PATH',
        '--container', 'Container')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        documents = list(yaml.safe_load_all(f))
    path = documents[1]['paths'][0]

    control_client.expect('paths', {})
    control_client.expect('mount')

    cli('container', 'mount', 'Container')

    command = control_client.calls['mount']['items']
    assert command[0]['storage']['owner'] == '0xaaa'

    assert sorted(command[0]['paths']) == sorted([
        f'/.users/0xaaa{path}',
        '/.users/0xaaa/PATH',
        '/.users/0xaaa/c1/c2/title',
        '/.users/0xaaa/c3/title',
        '/.users/0xaaa/c1/c2/c3/title',
        '/.users/0xaaa/c3/c1/c2/title',
        '/c1/c2/title',
        '/c3/title',
        '/c1/c2/c3/title',
        '/c3/c1/c2/title',
        path,
        '/PATH',
    ])

    modify_file(base_dir / 'config.yaml', "'@default': '0xaaa'", '')

    # The command should not contain the default path.
    cli('container', 'mount', 'Container')

    command = control_client.calls['mount']['items']
    assert command[0]['storage']['owner'] == '0xaaa'
    assert command[0]['paths'] == [
        f'/.users/0xaaa{path}',
        '/.users/0xaaa/PATH',
        '/.users/0xaaa/c1/c2/title',
        '/.users/0xaaa/c3/title',
        '/.users/0xaaa/c1/c2/c3/title',
        '/.users/0xaaa/c3/c1/c2/title',
    ]
    assert command[0]['extra']['trusted_owner'] is None


def test_container_wrong_signer(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('user', 'create', 'User2', '--key', '0xbbb')

    cli('container', 'create', 'Container', '--path', '/PATH', '--user', 'User2')

    modify_file(base_dir / 'containers/Container.container.yaml',
                "owner: '0xbbb'", "owner: '0xaaa'")

    with pytest.raises(ManifestError, match='Manifest owner does not have access to signer key'):
        cli('storage', 'create', 'local', 'Storage', '--path', '/PATH',
            '--container', 'Container')


## Status


def test_status(cli, control_client):
    control_client.expect('info', {
        '1': {
            'paths': ['/path1', '/path1.1'],
            'type': 'local',
            'extra': {},
        },
        '2': {
            'paths': ['/path2', '/path2.1'],
            'type': 's3',
            'extra': {},
        },
    })

    result = cli('status', capture=True)
    out_lines = result.splitlines()
    assert '/path1' in out_lines
    assert '  storage: local' in out_lines
    assert '    /path1' in out_lines
    assert '    /path1.1' in out_lines
    assert '/path2' in out_lines
    assert '  storage: s3' in out_lines
    assert '    /path2' in out_lines
    assert '    /path2.1' in out_lines


## Bridge


def test_bridge_create(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('user', 'create', 'RefUser', '--key', '0xbbb', '--path', '/OriginalPath')

    cli('bridge', 'create', 'Bridge',
        '--ref-user', 'RefUser',
        '--ref-user-location', 'https://example.com/RefUser.yaml',
        '--ref-user-path', '/ModifiedPath',
    )

    data = (base_dir / 'bridges/Bridge.bridge.yaml').read_text()
    assert 'user: https://example.com/RefUser.yaml' in data
    assert 'pubkey: key.0xbbb' in data
    assert '- /ModifiedPath' in data
    assert '- /OriginalPath' not in data


# Test the CLI tools directly (cannot easily use above-mentioned methods because of demonization)

def wl_call(base_config_dir, *args):
    subprocess.check_call(['./wl', '--base-dir', base_config_dir, *args])

# container-sync


def test_cli_container_sync(tmpdir, cleanup):
    base_config_dir = tmpdir / '.wildland'
    base_data_dir = tmpdir / 'wldata'
    storage1_data = base_data_dir / 'storage1'
    storage2_data = base_data_dir / 'storage2'

    os.mkdir(base_config_dir)
    os.mkdir(base_data_dir)
    os.mkdir(storage1_data)
    os.mkdir(storage2_data)

    cleanup(lambda: wl_call(base_config_dir, 'container', 'stop-sync', 'AliceContainer'))

    wl_call(base_config_dir, 'start')
    wl_call(base_config_dir, 'user', 'create', 'Alice')
    wl_call(base_config_dir, 'container', 'create',
            '--user', 'Alice', '--path', '/Alice', 'AliceContainer')
    wl_call(base_config_dir, 'storage', 'create', 'local',
            '--container', 'AliceContainer', '--path', storage1_data)
    wl_call(base_config_dir, 'storage', 'create', 'local',
            '--container', 'AliceContainer', '--path', storage2_data)
    wl_call(base_config_dir, 'container', 'sync', 'AliceContainer')

    time.sleep(1)

    with open(storage1_data / 'testfile', 'w') as f:
        f.write("test data")

    time.sleep(1)

    assert (storage2_data / 'testfile').exists()
    with open(storage2_data / 'testfile') as file:
        assert file.read() == 'test data'


# Storage sets

def setup_storage_sets(config_dir):
    os.mkdir(config_dir / 'templates')
    data_dict = {
        'path': f'{config_dir}' + '/{{ uuid }}',
        'type': 'local'
    }
    yaml.dump(data_dict, open(config_dir / 'templates/t1.template.jinja', 'w'))
    yaml.dump(data_dict, open(config_dir / 'templates/t2.template.jinja', 'w'))
    yaml.dump(data_dict, open(config_dir / 'templates/t3.template.jinja', 'w'))


def test_cli_set_add(cli, base_dir):
    setup_storage_sets(base_dir)
    cli('storage-set', 'add', '--template', 't1', '--inline', 't2', 'set1')
    cli('storage-set', 'add', '--inline', 't3', '--inline', 't2', 'set2')

    with open(base_dir / 'templates/set1.set.yaml', 'r') as f:
        read_data = yaml.load(f)
        assert read_data == {'name': 'set1',
                             'templates':
                                 [{'file': 't1.template.jinja', 'type': 'file'},
                                  {'file': 't2.template.jinja', 'type': 'inline'}]}
    with open(base_dir / 'templates/set2.set.yaml', 'r') as f:
        read_data = yaml.load(f)
        assert read_data == {'name': 'set2',
                             'templates':
                                 [{'file': 't3.template.jinja', 'type': 'inline'},
                                  {'file': 't2.template.jinja', 'type': 'inline'}]}


def test_cli_set_list(cli, base_dir):
    setup_storage_sets(base_dir)
    cli('storage-set', 'add', '--template', 't1', '--inline', 't2', 'set1')
    cli('storage-set', 'add', '--inline', 't3', '--inline', 't2', 'set2')

    result = cli('storage-set', 'list', capture=True)
    out_lines = [l.strip() for l in result.splitlines()]
    assert 't1' in out_lines
    assert 't2' in out_lines
    assert 't3' in out_lines
    assert 'set1 (file: t1) (inline: t2)' in out_lines
    assert 'set2 (inline: t3, t2)' in out_lines


def test_cli_set_del(cli, base_dir):
    setup_storage_sets(base_dir)
    cli('storage-set', 'add', '--template', 't1', '--inline', 't2', 'set1')

    expected_file = base_dir / 'templates/set1.set.yaml'
    assert expected_file.exists()

    cli('storage-set', 'remove', 'set1')

    assert not expected_file.exists()


def test_cli_set_use_inline(cli, base_dir):
    os.mkdir(base_dir / 'templates')
    data_dict = {
        'path':  f'{base_dir}' + '/{{ title }}',
        'type': 'local'
    }

    yaml.dump(data_dict, open(base_dir / 'templates/title.template.jinja', 'w'))
    cli('storage-set', 'add', '--inline', 'title', 'set1')
    cli('user', 'create', 'User')

    cli('container', 'create', 'Container', '--path', '/PATH', '--title', 'Test',
        '--storage-set', 'set1')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        output_lines = [line.strip() for line in f.readlines()]

        assert f'- path: {base_dir}/Test' in output_lines
        assert 'type: local' in output_lines

    assert (base_dir / 'Test').exists()


def test_cli_set_use_file(cli, base_dir):
    os.mkdir(base_dir / 'templates')
    data_dict = {
        'path':  f'{base_dir}' + '/{{ title }}',
        'type': 'local'
    }

    yaml.dump(data_dict, open(base_dir / 'templates/title.template.jinja', 'w'))
    cli('storage-set', 'add', '--template', 'title', 'set1')
    cli('user', 'create', 'User')

    cli('container', 'create', 'Container', '--path', '/PATH', '--title', 'Test',
        '--storage-set', 'set1')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        output_lines = [line.strip() for line in f.readlines()]

        assert f'- file://localhost{base_dir}/storage/set1.storage.yaml' in output_lines

    assert (base_dir / 'Test').exists()


def test_cli_set_missing_title(cli, base_dir):
    os.mkdir(base_dir / 'templates')
    data_dict = {
        'path':  f'{base_dir}' +
                 '/{% if title is defined -%} {{ title }} {% else -%} test {% endif %}',
        'type': 'local'
    }

    yaml.dump(data_dict, open(base_dir / 'templates/title.template.jinja', 'w'))
    cli('storage-set', 'add', '--inline', 'title', 'set1')
    cli('user', 'create', 'User')

    cli('container', 'create', 'Container', '--path', '/PATH', '--storage-set', 'set1')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        output_lines = [line.strip() for line in f.readlines()]

        assert f'- path: {base_dir}/test' in output_lines
        assert 'type: local' in output_lines


def test_cli_set_missing_param(cli, base_dir):
    os.mkdir(base_dir / 'templates')
    data_dict = {
        'path':  f'{base_dir}' + '{{ title }}',
        'type': 'local'
    }

    yaml.dump(data_dict, open(base_dir / 'templates/title.template.jinja', 'w'))
    cli('storage-set', 'add', '--inline', 'title', 'set1')
    cli('user', 'create', 'User')

    with pytest.raises(CliError, match='\'title\' is undefined'):
        cli('container', 'create',
            'Container', '--path', '/PATH', '--storage-set', 'set1', capture=True)

    assert not (base_dir / 'containers/Container.container.yaml').exists()


def test_cli_set_local_dir(cli, base_dir):
    os.mkdir(base_dir / 'templates')
    data_dict = {
        'path':  f'{base_dir}' + '/{{ local_dir[1:] }}',
        'type': 'local'
    }

    yaml.dump(data_dict, open(base_dir / 'templates/title.template.jinja', 'w'))
    cli('storage-set', 'add', '--inline', 'title', 'set1')
    cli('user', 'create', 'User')

    cli('container', 'create', 'Container', '--path', '/PATH', '--title', 'Test',
        '--storage-set', 'set1', '--local-dir', '/test/test')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        output_lines = [line.strip() for line in f.readlines()]

        assert f'- path: {base_dir}/test/test' in output_lines
        assert 'type: local' in output_lines

    assert (base_dir / 'test/test').exists()


def test_user_create_default_set(cli, base_dir):
    setup_storage_sets(base_dir)
    cli('user', 'create', 'User')
    cli('storage-set', 'add', '--template', 't1', '--inline', 't2', 'set')
    cli('storage-set', 'set-default', '--user', 'User', 'set')

    with open(base_dir / 'config.yaml') as f:
        data = f.read()

    config = yaml.load(data)
    default_user = config["@default-owner"]
    assert f'\'{default_user}\': set' in data


def test_cli_set_use_default(cli, base_dir):
    setup_storage_sets(base_dir)
    cli('user', 'create', 'User')
    cli('storage-set', 'add', '--template', 't1', 'set')
    cli('storage-set', 'set-default', '--user', 'User', 'set')

    cli('container', 'create', 'Container', '--path', '/PATH', '--title', 'Test')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        output_lines = [line.strip() for line in f.readlines()]
        print(output_lines)

        assert f'- file://localhost{base_dir}/storage/set.storage.yaml' in output_lines


def test_cli_set_use_def_storage(cli, base_dir):
    setup_storage_sets(base_dir)
    cli('user', 'create', 'User')
    cli('storage-set', 'add', '--template', 't1', 'set')
    cli('storage-set', 'set-default', '--user', 'User', 'set')

    cli('container', 'create', 'Container', '--path', '/PATH', '--title', 'Test')
    cli('storage', 'create-from-set', 'Container')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        output_lines = [line.strip() for line in f.readlines()]
        print(output_lines)

        assert f'- file://localhost{base_dir}/storage/set.storage.yaml' in output_lines
