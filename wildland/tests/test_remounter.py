# Wildland Project
#
# Copyright (C) 2021 Golem Foundation,
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

# pylint: disable=missing-docstring,redefined-outer-name,unused-argument
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import List, Tuple, Callable, Dict
from unittest import mock

import pytest

from wildland.wildland_object.wildland_object import WildlandObject
from ..client import Client
from ..container import Container
from ..control_client import ControlClientError
from ..manifest.manifest import ManifestError
from ..remounter import Remounter

DUMMY_BACKEND_UUID0 = '00000000-0000-0000-000000000000'
DUMMY_BACKEND_UUID1 = '11111111-1111-1111-111111111111'


def get_container_uuid_from_uuid_path(uuid_path: str):
    match = re.search('/.uuid/(.+?)$', uuid_path)
    return match.group(1) if match else ''


@pytest.fixture
def setup(base_dir, cli, control_client):
    control_client.expect('status', {})
    os.mkdir(base_dir / 'manifests')
    os.mkdir(base_dir / 'storage1')
    os.mkdir(base_dir / 'storage2')
    os.mkdir(base_dir / 'storage3')

    patch_uuid = mock.patch('uuid.uuid4', return_value=DUMMY_BACKEND_UUID0)
    patch_uuid.start()

    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('user', 'create', 'User2', '--key', '0xbbb', '--path', '/users/User2')

    cli('container', 'create', 'Infra', '--path', '/.manifests',
        '--path', '/.uuid/0000000000-1111-0000-0000-000000000000',
        '--no-encrypt-manifest', '--update-user')
    cli('storage', 'create', 'local', 'Infra1',
        '--location', base_dir / 'manifests',
        '--container', 'Infra')
    cli('container', 'create', 'Container1', '--path', '/path',
        '--path', '/.uuid/0000000000-1111-0000-1111-000000000000',
        '--no-encrypt-manifest')
    cli('storage', 'create', 'local', 'Storage1',
        '--location', base_dir / 'storage1',
        '--container', 'Container1',
        '--trusted', '--no-inline')

    cli('container', 'create', 'Container2', '--no-encrypt-manifest',
        '--path', '/.uuid/0000000000-1111-1111-1111-000000000000',
        '--path', '/other/path')
    cli('storage', 'create', 'local', 'Storage2',
        '--location', base_dir / 'storage2',
        '--container', 'Container2', '--no-inline')

    cli('container', 'create', 'C.User2',
        '--path', '/.uuid/0000000000-2222-0000-1111-000000000000',
        '--owner', 'User2',
        '--path', '/users/User2',
        '--update-user', '--no-encrypt-manifest')
    cli('storage', 'create', 'local', 'Storage3',
        '--location', base_dir / 'storage3',
        '--container', 'C.User2', '--no-inline',
        '--manifest-pattern', '/.manifests/*.yaml')

    shutil.copy(base_dir / 'containers/Container1.container.yaml',
                base_dir / 'manifests/Container1.yaml')
    shutil.copy(base_dir / 'containers/Container2.container.yaml',
                base_dir / 'manifests/Container2.yaml')

    infra_path = f'/.users/0xaaa/.uuid/0000000000-1111-0000-0000-000000000000/' \
        f'.backends/{DUMMY_BACKEND_UUID0}'
    control_client.add_storage_paths(0, [infra_path, '/.manifests'])

    patch_uuid.stop()

@pytest.fixture
def client(setup, base_dir):
    # pylint: disable=unused-argument
    client = Client(base_dir=base_dir)
    return client


class TerminateRemounter(Exception):
    pass


@dataclass
class ExpectedMount:
    owner: str

    paths: List[PurePosixPath]
    #: backend-id -> storage-id
    backends: Dict[str, int]


class RemounterWrapper(Remounter):
    def __init__(self, *args, control_client, **kwargs):
        super().__init__(*args, **kwargs)
        # list of:
        # - storages to mount as ExpectedMount objects
        #   storage-ids are used to mock given storage as mounted
        # - storages to unmount
        # - callable to apply modifications after processing request
        self.expected_actions: List[Tuple[List[ExpectedMount], List[int], Callable]] = []
        self.call_counter = 0
        self.control_client = control_client

    def expect_action(self, to_mount, to_unmount, callback):
        """
        Register expected action to be called by Remounter.
        Actions are expected in order of expect_action() calls.
        """
        self.expected_actions.append((to_mount, to_unmount, callback))

    def mount_pending(self):
        """
        Mock override real mount_pending() to check if queued operations match expectations
        registered with expect_action() calls.
        """
        assert self.call_counter < len(self.expected_actions), \
            f'expected only {len(self.expected_actions)} remounter iterations'
        to_mount, to_unmount, callback = self.expected_actions[self.call_counter]
        self.call_counter += 1

        assert len(self.to_mount) == len(to_mount), f'expected {to_mount}, actual {self.to_mount}'
        # TODO: sort
        for expected, actual in zip(to_mount, self.to_mount):
            # container
            assert expected.owner == actual[0].owner
            assert expected.paths == actual[0].paths
            # backends
            assert len(expected.backends) == len(actual[1])
            storage_id = None
            for expected_b, actual_b in zip(
                    sorted(expected.backends.items()),
                    sorted(actual[1], key=lambda s: s.backend_id)):
                assert expected_b[0] == actual_b.backend_id
                if actual_b.is_primary:
                    storage_id = expected_b[1]
                # register as mounted - backend specific path
                uuid = get_container_uuid_from_uuid_path(str(expected.paths[0]))
                self.control_client.add_storage_paths(
                    expected_b[1],
                    [f'/.users/{expected.owner}:/.backends/{uuid}/{expected_b[0]}']
                )

                # calculate storage tag, so params/paths change will be detected
                mount_paths = self.fs_client.get_storage_mount_paths(actual[0], actual_b, actual[2])
                tag = self.fs_client.get_storage_tag(mount_paths, actual_b.params)
                self.control_client.results['info'][expected_b[1]]['extra']['tag'] = tag

            # if there is primary storage, mount under generic paths too
            if storage_id is not None:
                self.control_client.add_storage_paths(
                    storage_id,
                    [f'/.users/{expected.owner}:{path}' for path in expected.paths]
                )
        self.to_mount.clear()

        # check to_unmount
        assert len(self.to_unmount) == len(to_unmount), \
            f'call {self.call_counter-1}: expected {to_unmount}, actual {self.to_unmount}'
        assert set(self.to_unmount) == set(to_unmount), \
            f'call {self.call_counter-1}: expected {to_unmount}, actual {self.to_unmount}'
        for storage_id in to_unmount:
            self.control_client.del_storage(storage_id)
        self.to_unmount.clear()

        self.fs_client.clear_cache()

        if callback is not None:
            callback()

    def unmount_pending(self):
        """
        Do nothing on unmount. to_unmount() queue is already checked in mount_pending()
        """

    def check(self):
        not_executed = self.expected_actions[self.call_counter:]
        assert not not_executed, \
            "The following actions were not executed: {!r}".format(not_executed)


def test_single_path(cli, client, control_client, base_dir):
    # simulate mounted container
    (base_dir / 'wildland/.manifests').mkdir(parents=True)
    shutil.copy(base_dir / 'containers/Container1.container.yaml',
                base_dir / 'wildland/.manifests/Container1.yaml')

    pattern = '/.manifests/Container1.yaml'
    remounter = RemounterWrapper(client, client.fs_client,
                                 [str(base_dir / ('wildland' + pattern))],
                                 control_client=control_client)
    control_client.expect('add-watch', 1)
    control_client.queue_event([
        {'watch-id': 1, 'type': 'modify', 'path': 'Container1.yaml'}])
    # interrupt after processing all events
    control_client.queue_event(TerminateRemounter())

    def modify_container():
        cli('container', 'modify', 'add-path', '--path', '/new/path', 'Container1')
        shutil.copy(base_dir / 'containers/Container1.container.yaml',
                    base_dir / 'wildland/.manifests/Container1.yaml')

    # initial mount
    remounter.expect_action(
        [ExpectedMount(
            '0xaaa',
            [PurePosixPath('/.uuid/0000000000-1111-0000-1111-000000000000'),
             PurePosixPath('/path')],
            {DUMMY_BACKEND_UUID0: 1}
        )], [], modify_container
    )
    # after changing container
    remounter.expect_action(
        [ExpectedMount(
            '0xaaa',
            [PurePosixPath('/.uuid/0000000000-1111-0000-1111-000000000000'),
             PurePosixPath('/path'),
             PurePosixPath('/new/path')],
            {DUMMY_BACKEND_UUID0: 1}
        )], [], None
    )
    with pytest.raises(TerminateRemounter):
        remounter.run()
    remounter.check()
    assert control_client.calls['add-watch'] == {
        'storage_id': 0,
        'pattern': 'Container1.yaml'}


def test_glob_with_broken(client, control_client, base_dir):
    # simulate mounted container
    (base_dir / 'wildland/.manifests').mkdir(parents=True)
    shutil.copy(base_dir / 'containers/Container2.container.yaml',
                base_dir / 'wildland/.manifests/Container2.yaml')
    # initially broken Container1 manifest
    with open(base_dir / 'wildland/.manifests/Container1.yaml', 'w') as f:
        f.write('broken manifest')

    pattern = '/.manifests/Container*.yaml'
    remounter = RemounterWrapper(client, client.fs_client,
                                 [str(base_dir / ('wildland' + pattern))],
                                 additional_patterns=['/.manifests/Other*.yaml'],
                                 control_client=control_client)
    control_client.expect('add-watch', 1)
    control_client.queue_event([
        {'watch-id': 1, 'type': 'modify', 'path': 'Container1.yaml'}])
    # interrupt after processing all events
    control_client.queue_event(TerminateRemounter())

    def fix_manifest():
        shutil.copy(base_dir / 'containers/Container1.container.yaml',
                    base_dir / 'wildland/.manifests/Container1.yaml')

    # initial mount
    remounter.expect_action(
        [ExpectedMount(
            '0xaaa',
            [PurePosixPath('/.uuid/0000000000-1111-1111-1111-000000000000'),
            PurePosixPath('/other/path')],
            {DUMMY_BACKEND_UUID0: 1}
        )], [], fix_manifest
    )
    # after changing container
    remounter.expect_action(
        [ExpectedMount(
            '0xaaa',
            [PurePosixPath('/.uuid/0000000000-1111-0000-1111-000000000000'),
             PurePosixPath('/path')],
            {DUMMY_BACKEND_UUID0: 2}
        )], [], None
    )

    with pytest.raises(TerminateRemounter):
        remounter.run()
    remounter.check()
    assert control_client.all_calls['add-watch'] == [
        {'storage_id': 0,
         'pattern': 'Other*.yaml'},
        {'storage_id': 0,
         'pattern': 'Container*.yaml'},
    ]


def test_glob_add_remove(cli, client, control_client, base_dir):
    # simulate mounted container
    (base_dir / 'wildland/.manifests').mkdir(parents=True)
    pattern = '/.manifests/Container*.yaml'
    remounter = RemounterWrapper(client, client.fs_client,
                                 [str(base_dir / ('wildland' + pattern))],
                                 control_client=control_client)
    control_client.expect('add-watch', 1)
    # initial events
    control_client.queue_event([])
    control_client.queue_event([
        {'watch-id': 1, 'type': 'create', 'path': 'Container1.yaml'}])
    control_client.queue_event([
        {'watch-id': 1, 'type': 'delete', 'path': 'Container1.yaml'}])
    # interrupt after processing all events
    control_client.queue_event(TerminateRemounter())

    def add_manifest():
        shutil.copy(base_dir / 'containers/Container1.container.yaml',
                    base_dir / 'wildland/.manifests/Container1.yaml')

    def del_manifest():
        (base_dir / 'wildland/.manifests/Container1.yaml').unlink()

    remounter.expect_action([], [], add_manifest)
    # after adding conatiner
    remounter.expect_action(
        [ExpectedMount(
            '0xaaa',
            [PurePosixPath('/.uuid/0000000000-1111-0000-1111-000000000000'),
             PurePosixPath('/path')],
            {DUMMY_BACKEND_UUID0: 1}
        )], [], del_manifest
    )
    remounter.expect_action([], [1], None)

    with pytest.raises(TerminateRemounter):
        remounter.run()
    remounter.check()


def test_add_remove_storage(cli, client, control_client, base_dir):
    # simulate mounted container
    (base_dir / 'wildland/.manifests').mkdir(parents=True)
    shutil.copy(base_dir / 'containers/Container1.container.yaml',
                base_dir / 'wildland/.manifests/Container1.yaml')
    pattern = '/.manifests/Container1.yaml'
    remounter = RemounterWrapper(client, client.fs_client,
                                 [str(base_dir / ('wildland' + pattern))],
                                 control_client=control_client)
    control_client.expect('add-watch', 1)
    control_client.queue_event([
        {'watch-id': 1, 'type': 'modify', 'path': 'Container1.yaml'}])
    control_client.queue_event([
        {'watch-id': 1, 'type': 'modify', 'path': 'Container1.yaml'}])
    # interrupt after processing all events
    control_client.queue_event(TerminateRemounter())

    def add_storage():
        with mock.patch('uuid.uuid4', return_value=DUMMY_BACKEND_UUID1):
            cli('storage', 'create', 'local', '--location', str(base_dir / 'storage2'),
                '--container', 'Container1')
        shutil.copy(base_dir / 'containers/Container1.container.yaml',
                    base_dir / 'wildland/.manifests/Container1.yaml')

    def del_storage():
        cli('container', 'modify', 'del-storage', '--storage', '1',
            'Container1')
        shutil.copy(base_dir / 'containers/Container1.container.yaml',
                    base_dir / 'wildland/.manifests/Container1.yaml')

    remounter.expect_action([ExpectedMount(
            '0xaaa',
            [PurePosixPath('/.uuid/0000000000-1111-0000-1111-000000000000'),
             PurePosixPath('/path')],
            {DUMMY_BACKEND_UUID0: 1}
    )], [], add_storage)
    # after adding storage
    remounter.expect_action(
        [ExpectedMount(
            '0xaaa',
            [PurePosixPath('/.uuid/0000000000-1111-0000-1111-000000000000'),
             PurePosixPath('/path')],
            {DUMMY_BACKEND_UUID1: 2}
    )], [], del_storage)
    remounter.expect_action([], [2], None)

    with pytest.raises(TerminateRemounter):
        remounter.run()
    remounter.check()


def test_modify_storage(cli, client, control_client, base_dir):
    with mock.patch('uuid.uuid4', return_value=DUMMY_BACKEND_UUID1):
        cli('storage', 'create', 'local', '--location', str(base_dir / 'storage2'),
            '--container', 'Container1')
    # simulate mounted container
    (base_dir / 'wildland/.manifests').mkdir(parents=True)
    shutil.copy(base_dir / 'containers/Container1.container.yaml',
                base_dir / 'wildland/.manifests/Container1.yaml')
    pattern = '/.manifests/Container1.yaml'
    remounter = RemounterWrapper(client, client.fs_client,
                                 [str(base_dir / ('wildland' + pattern))],
                                 control_client=control_client)
    control_client.expect('add-watch', 1)
    control_client.queue_event([
        {'watch-id': 1, 'type': 'modify', 'path': 'Container1.yaml'}])
    control_client.queue_event([
        {'watch-id': 1, 'type': 'modify', 'path': 'Container1.yaml'}])
    # interrupt after processing all events
    control_client.queue_event(TerminateRemounter())

    def modify_storage():
        """modify one storage parameters (location)"""
        cli('container', 'modify', 'del-storage', '--storage', '1',
            'Container1')
        with mock.patch('uuid.uuid4', return_value=DUMMY_BACKEND_UUID1):
            cli('storage', 'create', 'local', '--location', str(base_dir / 'storage3'),
                '--container', 'Container1')
        shutil.copy(base_dir / 'containers/Container1.container.yaml',
                    base_dir / 'wildland/.manifests/Container1.yaml')

    def switch_primary():
        """change storages order without changing anything else"""
        cli('container', 'modify', 'del-storage', '--storage', '0',
            'Container1')
        with mock.patch('uuid.uuid4', return_value=DUMMY_BACKEND_UUID0):
            cli('storage', 'create', 'local', '--location', str(base_dir / 'storage1'),
                '--container', 'Container1')
        shutil.copy(base_dir / 'containers/Container1.container.yaml',
                    base_dir / 'wildland/.manifests/Container1.yaml')

    remounter.expect_action([ExpectedMount(
            '0xaaa',
            [PurePosixPath('/.uuid/0000000000-1111-0000-1111-000000000000'),
             PurePosixPath('/path')],
            {DUMMY_BACKEND_UUID0: 1, DUMMY_BACKEND_UUID1: 2}
    )], [], modify_storage)
    # after adding storage
    remounter.expect_action(
        [ExpectedMount(
            '0xaaa',
            [PurePosixPath('/.uuid/0000000000-1111-0000-1111-000000000000'),
             PurePosixPath('/path')],
            {DUMMY_BACKEND_UUID1: 2}
    )], [], switch_primary)
    remounter.expect_action([ExpectedMount(
            '0xaaa',
            [PurePosixPath('/.uuid/0000000000-1111-0000-1111-000000000000'),
             PurePosixPath('/path')],
            {DUMMY_BACKEND_UUID0: 1, DUMMY_BACKEND_UUID1: 2}
    )], [], None)

    with pytest.raises(TerminateRemounter):
        remounter.run()
    remounter.check()


class SearchMock:
    def __init__(self):
        # called for those paths
        self.wlpaths = []
        # return value for get_watch_params
        self.watch_params = ()
        # list of results on subsequent calls
        self.containers_results: List[List[Container]] = []

    def __call__(self, client, wlpath, *args, **kwargs):
        self.wlpaths.append(wlpath)
        return self

    def get_watch_params(self):
        return self.watch_params

    def read_container(self):
        result = self.containers_results.pop(0)
        for c in result:
            if isinstance(c, Exception):
                raise c
            yield c


@pytest.fixture
def search_mock():
    test_search = SearchMock()
    with mock.patch('wildland.remounter.Search') as search_mock:
        search_mock.return_value = test_search
        yield test_search


def test_wlpath_single(cli, client, search_mock, control_client):
    search_mock.watch_params = ([], {'/.manifests/Container1.yaml'})

    c1 = client.load_object_from_name(WildlandObject.Type.CONTAINER, 'Container1')

    cli('container', 'modify', 'add-path', '--path', '/new/path', 'Container1')

    c1_changed = client.load_object_from_name(WildlandObject.Type.CONTAINER, 'Container1')

    search_mock.containers_results = [
        [c1],
        [c1_changed],
    ]
    pattern = ':/containers/c1:'
    remounter = RemounterWrapper(client, client.fs_client,
                                 [pattern],
                                 control_client=control_client)

    control_client.expect('add-watch', 1)
    control_client.queue_event([
        {'watch-id': 1, 'type': 'create', 'path': 'Container1.yaml',
         'pattern': 'Container1.yaml'}])
    control_client.queue_event([
        {'watch-id': 1, 'type': 'modify', 'path': 'Container1.yaml',
         'pattern': 'Container1.yaml'}])
    # interrupt after processing all events
    control_client.queue_event(TerminateRemounter())

    # initial mount
    remounter.expect_action(
        [ExpectedMount(
            '0xaaa',
            [PurePosixPath('/.uuid/0000000000-1111-0000-1111-000000000000'),
             PurePosixPath('/path')],
            {DUMMY_BACKEND_UUID0: 1}
        )], [], None
    )
    # after changing container
    remounter.expect_action(
        [ExpectedMount(
            '0xaaa',
            [PurePosixPath('/.uuid/0000000000-1111-0000-1111-000000000000'),
             PurePosixPath('/path'),
             PurePosixPath('/new/path')],
            {DUMMY_BACKEND_UUID0: 1}
        )], [], None
    )
    with pytest.raises(TerminateRemounter):
        remounter.run()
    remounter.check()
    assert control_client.calls['add-watch'] == {
        'storage_id': 0,
        'pattern': 'Container1.yaml'}


def test_wlpath_delete_container(client, search_mock, control_client):
    search_mock.watch_params = ([], {'/.manifests/Container1.yaml'})

    c1 = client.load_object_from_name(WildlandObject.Type.CONTAINER, 'Container1')
    c2 = client.load_object_from_name(WildlandObject.Type.CONTAINER, 'Container2')

    search_mock.containers_results = [
        [c1, c2],
        [c1],
        [],
    ]
    pattern = ':/containers/c1:'
    remounter = RemounterWrapper(client, client.fs_client,
                                 [pattern],
                                 control_client=control_client)

    control_client.expect('add-watch', 1)
    control_client.queue_event([
        {'watch-id': 1, 'type': 'create', 'path': 'Container1.yaml',
         'pattern': 'Container1.yaml'}])
    # modify should also cause the WL path to be re-evaluated
    control_client.queue_event([
        {'watch-id': 1, 'type': 'modify', 'path': 'Container1.yaml',
         'pattern': 'Container1.yaml'}])
    control_client.queue_event([
        {'watch-id': 1, 'type': 'delete', 'path': 'Container1.yaml',
         'pattern': 'Container1.yaml'}])
    # interrupt after processing all events
    control_client.queue_event(TerminateRemounter())

    # initial mount
    remounter.expect_action(
        [ExpectedMount(
            '0xaaa',
            [PurePosixPath('/.uuid/0000000000-1111-0000-1111-000000000000'),
             PurePosixPath('/path')],
            {DUMMY_BACKEND_UUID0: 1}
        ), ExpectedMount(
            '0xaaa',
            [PurePosixPath('/.uuid/0000000000-1111-1111-1111-000000000000'),
             PurePosixPath('/other/path')],
            {DUMMY_BACKEND_UUID0: 2}
        )], [], None
    )
    remounter.expect_action([], [2], None)
    remounter.expect_action([], [1], None)

    with pytest.raises(TerminateRemounter):
        remounter.run()
    remounter.check()
    assert control_client.calls['add-watch'] == {
        'storage_id': 0,
        'pattern': 'Container1.yaml'}


def test_wlpath_multiple_patterns(cli, client, search_mock, control_client):
    search_mock.watch_params = ([], {'/.manifests/Container1.yaml', '/.manifests/Container2.yaml'})

    c1 = client.load_object_from_name(WildlandObject.Type.CONTAINER, 'Container1')
    c2 = client.load_object_from_name(WildlandObject.Type.CONTAINER, 'Container2')

    cli('container', 'modify', 'add-path', '--path', '/new/path', 'Container1')
    cli('container', 'modify', 'add-path', '--path', '/yet/another/path', 'Container2')

    c1_changed = client.load_object_from_name(WildlandObject.Type.CONTAINER, 'Container1')
    c2_changed = client.load_object_from_name(WildlandObject.Type.CONTAINER, 'Container2')

    search_mock.containers_results = [
        [c1, c2],
        [c1_changed, c2_changed],
    ]
    pattern = ':*:'
    remounter = RemounterWrapper(client, client.fs_client,
                                 [pattern],
                                 control_client=control_client)

    control_client.expect('add-watch', 1)
    control_client.queue_event([
        {'watch-id': 1, 'type': 'create', 'path': 'Container1.yaml',
         'pattern': 'Container1.yaml'},
        {'watch-id': 1, 'type': 'create', 'path': 'Container2.yaml',
         'pattern': 'Container2.yaml'},
    ])
    # modify should also cause the WL path to be re-evaluated
    control_client.queue_event([
        {'watch-id': 1, 'type': 'modify', 'path': 'Container1.yaml',
         'pattern': 'Container1.yaml'},
        {'watch-id': 1, 'type': 'modify', 'path': 'Container2.yaml',
         'pattern': 'Container2.yaml'}
    ])
    # interrupt after processing all events
    control_client.queue_event(TerminateRemounter())

    # initial mount
    remounter.expect_action(
        [ExpectedMount(
            '0xaaa',
            [PurePosixPath('/.uuid/0000000000-1111-0000-1111-000000000000'),
             PurePosixPath('/path')],
            {DUMMY_BACKEND_UUID0: 1}
        ), ExpectedMount(
            '0xaaa',
            [PurePosixPath('/.uuid/0000000000-1111-1111-1111-000000000000'),
             PurePosixPath('/other/path')],
            {DUMMY_BACKEND_UUID0: 2}
        )], [], None
    )
    remounter.expect_action(
        [ExpectedMount(
            '0xaaa',
            [PurePosixPath('/.uuid/0000000000-1111-0000-1111-000000000000'),
             PurePosixPath('/path'),
             PurePosixPath('/new/path')],
            {DUMMY_BACKEND_UUID0: 1}
        ), ExpectedMount(
            '0xaaa',
            [PurePosixPath('/.uuid/0000000000-1111-1111-1111-000000000000'),
             PurePosixPath('/other/path'),
             PurePosixPath('/yet/another/path')],
            {DUMMY_BACKEND_UUID0: 2}
        )], [], None
    )

    with pytest.raises(TerminateRemounter):
        remounter.run()
    remounter.check()
    assert sorted(control_client.all_calls['add-watch'],
                  key=lambda c: c['pattern']) == [
        {'storage_id': 0,
         'pattern': 'Container1.yaml'},
        {'storage_id': 0,
         'pattern': 'Container2.yaml'},
    ]


def test_wlpath_iterate_error(cli, client, search_mock, control_client):
    search_mock.watch_params = ([], {'/.manifests/Container1.yaml'})

    c1 = client.load_object_from_name(WildlandObject.Type.CONTAINER, 'Container1')

    search_mock.containers_results = [
        [c1, ManifestError('container load failed')],
        [ManifestError('container load failed')],
        [],
    ]
    pattern = ':/containers/c1:'
    remounter = RemounterWrapper(client, client.fs_client,
                                 [pattern],
                                 control_client=control_client)

    control_client.expect('add-watch', 1)
    control_client.queue_event([
        {'watch-id': 1, 'type': 'create', 'path': 'Container1.yaml',
         'pattern': 'Container1.yaml'},
    ])
    control_client.queue_event([
        {'watch-id': 1, 'type': 'modify', 'path': 'Container1.yaml',
         'pattern': 'Container1.yaml'},
    ])
    control_client.queue_event([
        {'watch-id': 1, 'type': 'modify', 'path': 'Container1.yaml',
         'pattern': 'Container1.yaml'},
    ])
    # interrupt after processing all events
    control_client.queue_event(TerminateRemounter())

    # initial mount
    remounter.expect_action(
        [ExpectedMount(
            '0xaaa',
            [PurePosixPath('/.uuid/0000000000-1111-0000-1111-000000000000'),
             PurePosixPath('/path')],
            {DUMMY_BACKEND_UUID0: 1}
        )], [], None
    )
    # should not unmount anything if search failed
    remounter.expect_action([], [], None)
    remounter.expect_action([], [1], None)

    with pytest.raises(TerminateRemounter):
        remounter.run()
    remounter.check()
    assert control_client.calls['add-watch'] == {
        'storage_id': 0,
        'pattern': 'Container1.yaml'
    }
    # not really expected in this test
    assert 'info' not in control_client.calls
    del control_client.results['info']


def test_wlpath_change_pattern(cli, base_dir, client, search_mock, control_client):
    # pylint: disable=protected-access
    search_mock.watch_params = ([], {'/.manifests/Container1.yaml'})

    with mock.patch('uuid.uuid4', return_value=DUMMY_BACKEND_UUID1):
        cli('storage', 'create', 'local', 'Infra1',
            '--location', base_dir / 'manifests',
            '--container', 'Infra')

    c1 = client.load_object_from_name(WildlandObject.Type.CONTAINER, 'Container1')
    c2 = client.load_object_from_name(WildlandObject.Type.CONTAINER, 'Container2')
    infra = client.load_object_from_name(WildlandObject.Type.CONTAINER, 'Infra')
    infra_s0 = client.load_object_from_dict(WildlandObject.Type.STORAGE,
                                            infra._storage_cache[0].storage,
                                            infra.owner, infra.paths[0])
    infra_s1 = client.load_object_from_dict(WildlandObject.Type.STORAGE,
                                            infra._storage_cache[1].storage,
                                            infra.owner, infra.paths[0])
    search_mock.containers_results = [
        [c1],
        [c1, c2],
        [c1],
    ]
    pattern = ':/containers/c1:'
    remounter = RemounterWrapper(client, client.fs_client,
                                 [pattern],
                                 control_client=control_client)

    control_client.expect('add-watch', 1)
    control_client.queue_event([
        {'watch-id': 1, 'type': 'create', 'path': 'Container1.yaml',
         'pattern': 'Container1.yaml'},
    ])
    control_client.queue_event([
        {'watch-id': 1, 'type': 'create', 'path': 'Container2.yaml',
         'pattern': 'Container2.yaml'},
    ])
    # old pattern should still work
    control_client.queue_event([
        {'watch-id': 1, 'type': 'modify', 'path': 'Container1.yaml',
         'pattern': 'Container1.yaml'},
    ])
    # interrupt after processing all events
    control_client.queue_event(TerminateRemounter())

    def change_watch_params():
        control_client.expect('mount')
        search_mock.watch_params = ([(infra, [infra_s0], [], None)],
                                    {'/.manifests/Container2.yaml'})

    def fail_mount():
        control_client.expect('mount', ControlClientError('mount failed'))
        search_mock.watch_params = ([(infra, [infra_s1], [], None)],
                                    {'/.manifests/Container3.yaml'})

    # initial mount
    remounter.expect_action(
        [ExpectedMount(
            '0xaaa',
            [PurePosixPath('/.uuid/0000000000-1111-0000-1111-000000000000'),
             PurePosixPath('/path')],
            {DUMMY_BACKEND_UUID0: 1}
        )], [], change_watch_params
    )
    remounter.expect_action(
        [ExpectedMount(
            '0xaaa',
            [PurePosixPath('/.uuid/0000000000-1111-1111-1111-000000000000'),
             PurePosixPath('/other/path')],
            {DUMMY_BACKEND_UUID0: 2}
        )], [], fail_mount
    )
    remounter.expect_action([], [2], None)

    with pytest.raises(TerminateRemounter):
        remounter.run()
    remounter.check()
    assert control_client.all_calls['add-watch'] == [
        {
            'storage_id': 0,
            'pattern': 'Container1.yaml'
        },
        {
            'storage_id': 0,
            'pattern': 'Container2.yaml'
        },
    ]
    assert control_client.all_calls['mount'] == [
        {'items': [{
            'paths': [f'/.users/0xaaa:/.backends/{infra.uuid}/{DUMMY_BACKEND_UUID0}'],
            'remount': False,
            'storage': mock.ANY,
            'extra': mock.ANY,
        }]},
        {'items': [{
            'paths': [f'/.users/0xaaa:/.backends/{infra.uuid}/{DUMMY_BACKEND_UUID1}'],
            'remount': False,
            'storage': mock.ANY,
            'extra': mock.ANY,
        }]},
        # should retry on the next event
        {'items': [{
            'paths': [f'/.users/0xaaa:/.backends/{infra.uuid}/{DUMMY_BACKEND_UUID1}'],
            'remount': False,
            'storage': mock.ANY,
            'extra': mock.ANY,
        }]},
    ]


def test_failed_mount(control_client, client):
    del control_client.results['info']
    del control_client.results['paths']
    remounter = Remounter(client, client.fs_client, [])

    remounter.to_mount.append((mock.Mock, [], [], None))
    control_client.expect('mount', ControlClientError('mount failed'))
    # should catch the mount error
    remounter.mount_pending()
    # don't retry exactly the same operation
    assert remounter.to_mount == []


def test_failed_unmount(control_client, client):
    del control_client.results['info']
    del control_client.results['paths']
    remounter = Remounter(client, client.fs_client, [])

    remounter.to_unmount.append(1)
    remounter.to_unmount.append(2)
    control_client.expect('unmount', ControlClientError('mount failed'))
    # should catch the unmount error
    remounter.unmount_pending()
    # don't retry exactly the same operation
    assert remounter.to_unmount == []

    assert control_client.all_calls['unmount'] == [
        {'storage_id': 1},
        {'storage_id': 2},
    ]

# TODO:
# - container that fails to mount
# (it's rather a test for mount_multiple_containers? or even fs_base.py)
