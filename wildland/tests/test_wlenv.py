# Wildland Project
#
# Copyright (C) 2021 Golem Foundation
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
from wildland.wlenv import WLEnv


def assert_reload(reload_method):
    wlr = reload_method()
    assert wlr.success, wlr.errors[0].error_description


def assert_get(get_method, expected_value):
    wlr, result = get_method()
    assert wlr.success, wlr.errors
    assert expected_value == result


def assert_set(set_method, args, **kwargs):
    if isinstance(args, list):
        wlr = set_method(*args, **kwargs)
    else:
        wlr = set_method(args, **kwargs)
    assert wlr.success, wlr.errors


def assert_reset(reset_method, *args, **kwargs):
    wlr = reset_method(*args, **kwargs)
    assert wlr.success


def test_get_set_reset(base_dir):
    env = WLEnv(base_dir)

    params = {
            'user-dir': str(base_dir / 'us'),
            'storage-dir': str(base_dir / 'ss'),
            'cache-dir': str(base_dir / 'c'),
            'container-dir': str(base_dir / 'cs'),
            'bridge-dir': str(base_dir / 'bs'),
            'key-dir': str(base_dir / 'ks'),
            'template-dir': str(base_dir / 'ts'),
            'fs-socket-path': str(base_dir / 'wlf.sock'),
            'sync-socket-path': str(base_dir / 'wls.sock'),
            'alt-bridge-separator': True,
            'dummy': False,
            '@default': "0xaaa",
            '@default-owner': "0xbbb",
            'local-hostname': 'other',
            'local-owners': ["0xaaa", "0xbbb"],
            'default-containers': ["a", "b", "c"],
            'default-cache-template': "template",
        }
    env.config.default_fields['dummy'] = True
    default = env.config.default_fields.copy()

    for param in params:
        reset = True
        get = 'get_'
        param_name = param.replace("-", "_").replace('@', '')

        if param == '@default':
            param_name = 'default_user'
            reset = False
        elif param == '@default-owner':
            reset = False
        elif param == 'alt-bridge-separator':
            get = 'is_'
            reset = False
        elif param == 'dummy':
            param_name = 'dummy_sig_context'
            get = 'is_'
            reset = False

        env_get = env.__getattribute__(get + param_name)
        env_set = env.__getattribute__("set_" + param_name)

        assert_get(env_get, default[param])

        assert_set(env_set, params[param], save=False)
        assert_get(env_get, params[param])
        assert_reload(env.reload)
        assert_get(env_get, default[param])

        assert_set(env_set, params[param])
        assert_get(env_get, params[param])
        assert_reload(env.reload)
        assert_get(env_get, params[param])

        if reset:
            env_reset = env.__getattribute__("reset_" + param_name)

            assert_reset(env_reset, save=False)
            assert_get(env_get, default[param])
            assert_reload(env.reload)
            assert_get(env_get, params[param])

            assert_reset(env_reset)
            assert_get(env_get, default[param])
            assert_reload(env.reload)
            assert_get(env_get, default[param])


def test_default_remotes(base_dir):
    env = WLEnv(base_dir)

    wlr, result = env.get_default_remote_for_container('0000')
    assert not wlr.success
    assert result is None

    assert env.set_default_remote_for_container('0000', '1111').success
    assert env.set_default_remote_for_container('2222', '3333').success
    assert env.set_default_remote_for_container('4444', '6666').success

    wlr, remote = env.get_default_remote_for_container('0000')
    assert wlr.success
    assert remote == '1111'

    assert env.remove_default_remote_for_container('2222', '4444').success
    wlr, result = env.get_default_remote_for_container('2222')
    assert not wlr.success
    assert result is None

    assert env.reset_default_remotes().success
    wlr, result = env.get_default_remote_for_container('0000')
    assert not wlr.success
    assert result is None


def test_aliases(base_dir):
    env = WLEnv(base_dir)

    wlr, result = env.get_alias('superuser')
    assert not wlr.success
    assert result is None

    assert env.set_alias('superuser', '0xaaa').success
    assert env.set_alias('u1', '0xbbb').success
    assert env.set_alias('u2', '0xccc').success

    wlr, alias = env.get_alias('superuser')
    assert wlr.success
    assert alias == '0xaaa'

    env.remove_aliases('u1', 'u2')
    wlr, result = env.get_alias('u1')
    assert not wlr.success
    assert result is None

    assert env.reset_aliases().success
    wlr, result = env.get_alias('superuser')
    assert not wlr.success
    assert result is None


def test_local_owners(base_dir):
    env = WLEnv(base_dir)

    assert env.set_local_owners('0xaaa', '0xbbb').success

    wlr, correct = env.is_local_owner('0xaaa')
    assert wlr.success
    assert correct

    wlr, incorrect = env.is_local_owner('0xccc')
    assert wlr.success
    assert not incorrect

    assert env.add_local_owners('0xccc').success
    wlr, correct = env.is_local_owner('0xccc')
    assert wlr.success
    assert correct

    assert env.remove_local_owners('0xaaa', '0xbbb').success
    wlr, incorrect = env.is_local_owner('0xbbb')
    assert wlr.success
    assert not incorrect


def test_default_containers(base_dir):
    env = WLEnv(base_dir)

    assert env.set_default_containers('0000', '1111').success

    wlr, correct = env.is_default_container('0000')
    assert wlr.success
    assert correct

    wlr, incorrect = env.is_default_container('3333')
    assert wlr.success
    assert not incorrect

    assert env.add_default_containers('3333').success
    wlr, correct = env.is_default_container('3333')
    assert wlr.success
    assert correct

    assert env.remove_default_containers('0000', '1111').success
    wlr, incorrect = env.is_default_container('1111')
    assert wlr.success
    assert not incorrect


def test_paths(base_dir):
    env = WLEnv(base_dir)

    assert not env.set_user_dir('aaa').success
    assert not env.set_user_dir('aaa/bbb').success
