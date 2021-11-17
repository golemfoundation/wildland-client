# Wildland Project
#
# Copyright (C) 2021 Golem Foundation
#
# Authors:
#    Piotr K. Isajew  <piotr@wildland.io>
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

"""
Wildland environment for Linux systems.
"""
from pathlib import Path
from typing import Optional, Union, List
from functools import partial

from .config import Config
from .core.wildland_result import WildlandResult, WLError, wildland_result


class WLEnv:
    """
    Base environment for Wildland.
    """
    def __init__(self, base_dir=None):
        self.base_dir = base_dir
        self.config: Config = self.load_config(base_dir)

    @staticmethod
    def load_config(base_dir: str = None) -> Config:
        """
        load an instance of Config object, optionally
        using passed params to initialize it in a
        platform-specific way.
        """
        return Config.load(base_dir)

    @wildland_result
    def reload(self, base_dir: Optional[str] = None):
        """
        Reload configuration from config.yaml file.

        @param base_dir: Path to directory with configuration file: <base_dir>/config.yaml
        """
        base_dir = base_dir or self.base_dir
        self.config = self.load_config(base_dir)

    @wildland_result
    def reset(self, save: bool = False):
        """
        Set default values for configuration.

        @param save: if true, save the change to the config file.
        """
        if save:
            self.config.override_fields = {}
            self.config.update_and_save({})
        else:
            self.config.override_fields = self.config.default_fields.copy()

    def __get_update_method(self, save):
        return self.config.update_and_save if save else partial(self.config.override, dummy=False)

    def _get_param(self, param: str):
        result = self.config.get(param)
        return WildlandResult(), result  # handle None value

    def _set_param(self, param: str, value: Union[bool, str, List[str]], save: bool):
        config_update = self.__get_update_method(save)
        config_update({param: value})

    def _set_absolute_path(self, param: str, path: str, save: bool):
        if not Path(path).is_absolute():
            raise ValueError("Given value is not absolute path.")
        config_update = self.__get_update_method(save)
        config_update({param: path})

    def _reset_param(self, param: str, save: bool):
        default_value = self.config.default_fields[param]
        self.config.override({param : default_value})
        if save:
            self.config.remove_key_and_save(param)

    @wildland_result
    def get_user_dir(self):
        """
        Get the path to the user manifests directory.
        """
        return self._get_param('user-dir')

    @wildland_result
    def set_user_dir(self, user_dir: str, save: bool = True):
        """
        Set the path to the user manifests directory.

        @param user_dir: path to the directory
        @param save: if true, save the change to the config file.
        """
        self._set_absolute_path('user-dir', user_dir, save)

    @wildland_result
    def reset_user_dir(self, save: bool = True):
        """
        Reset the path to the user manifests directory to <base_dir>/users.

        @param save: if true, save the change to the config file.
        """
        self._reset_param('user-dir', save)

    @wildland_result
    def get_storage_dir(self):
        """
        Get the path to the storage manifests directory.
        """
        return self._get_param('storage-dir')

    @wildland_result
    def set_storage_dir(self, storage_dir: str, save: bool = True):
        """
        Set the path to the storage manifests directory.

        @param storage_dir: path to the directory
        @param save: if true, save the change to the config file.
        """
        self._set_absolute_path('storage-dir', storage_dir, save)

    @wildland_result
    def reset_storage_dir(self, save: bool = True):
        """
        Reset the path to the storage manifests directory to <base_dir>/storage.

        @param save: if true, save the change to the config file.
        """
        self._reset_param('storage-dir', save)

    @wildland_result
    def get_cache_dir(self):
        """
        Get the path for the wildland cache directory.
        """
        return self._get_param('cache-dir')

    @wildland_result
    def set_cache_dir(self, cache_dir: str, save: bool = True):
        """
        Set the path for the wildland cache directory.

        @param cache_dir: path to the directory
        @param save: if true, save the change to the config file.
        """
        self._set_absolute_path('cache-dir', cache_dir, save)

    @wildland_result
    def reset_cache_dir(self, save: bool = True):
        """
        Reset the path for the wildland cache directory to <base_dir>/cache.

        @param save: if true, save the change to the config file.
        """
        self._reset_param('cache-dir', save)

    @wildland_result
    def get_container_dir(self):
        """
        Get the path to the container manifests directory.
        """
        return self._get_param('container-dir')

    @wildland_result
    def set_container_dir(self, container_dir: str, save: bool = True):
        """
        Set the path to the container manifests directory.

        @param container_dir: path to the directory
        @param save: if true, save the change to the config file.
        """
        self._set_absolute_path('container-dir', container_dir, save)

    @wildland_result
    def reset_container_dir(self, save: bool = True):
        """
        Reset the path to the container manifests directory to <base_dir>/containers.

        @param save: if true, save the change to the config file.
        """
        self._reset_param('container-dir', save)

    @wildland_result
    def get_bridge_dir(self):
        """
        Get the path to the bridge manifests directory.
        """
        return self._get_param('bridge-dir')

    @wildland_result
    def set_bridge_dir(self, bridge_dir: str, save: bool = True):
        """
        Set the path to the bridge manifests directory.

        @param bridge_dir: path to the directory
        @param save: if true, save the change to the config file.
        """
        self._set_absolute_path('bridge-dir', bridge_dir, save)

    @wildland_result
    def reset_bridge_dir(self, save: bool = True):
        """
        Reset the path to the bridge manifests directory to <base_dir>/bridges.

        @param save: if true, save the change to the config file.
        """
        self._reset_param('bridge-dir', save)

    @wildland_result
    def get_key_dir(self):
        """
        Get the path to the key directory.
        """
        return self._get_param('key-dir')

    @wildland_result
    def set_key_dir(self, key_dir: str, save: bool = True):
        """
        Set the path to the key directory.

        @param key_dir: path to the directory
        @param save: if true, save the change to the config file.
        """
        self._set_absolute_path('key-dir', key_dir, save)

    @wildland_result
    def reset_key_dir(self, save: bool = True):
        """
        Reset the path to the key directory to <base_dir>/keys.

        @param save: if true, save the change to the config file.
        """
        self._reset_param('key-dir', save)

    @wildland_result
    def get_mount_dir(self):
        """
        Get the path where wildland will be mounted.
        """
        return self._get_param('mount-dir')

    @wildland_result
    def set_mount_dir(self, mount_dir: str, save: bool = True):
        """
        Set the path where wildland will be mounted.

        @param mount_dir: path to the directory
        @param save: if true, save the change to the config file.
        """
        self._set_absolute_path('mount-dir', mount_dir, save)

    @wildland_result
    def reset_mount_dir(self, save: bool = True):
        """
        Reset the path where wildland will be mounted to <home_dir>/wildland.

        @param save: if true, save the change to the config file.
        """
        self._reset_param('mount-dir', save)

    @wildland_result
    def get_template_dir(self):
        """
        Get the path to the templates directory.
        """
        return self._get_param('template-dir')

    @wildland_result
    def set_template_dir(self, template_dir: str, save: bool = True):
        """
        Set the path to the templates directory.

        @param template_dir: path to the directory
        @param save: if true, save the change to the config file.
        """
        self._set_absolute_path('template-dir', template_dir, save)

    @wildland_result
    def reset_template_dir(self, save: bool = True):
        """
        Reset the path to the template directory to <base_dir>/templates.

        @param save: if true, save the change to the config file.
        """
        self._reset_param('template-dir', save)

    @wildland_result
    def get_fs_socket_path(self):
        """
        Get the path to the fuse socket.
        """
        return self._get_param('fs-socket-path')

    @wildland_result
    def set_fs_socket_path(self, fs_socket_path: str, save: bool = True):
        """
        Set the path to the fuse socket.

        @param fs_socket_path: path to the socket
        @param save: if true, save the change to the config file.
        """
        self._set_absolute_path('fs-socket-path', fs_socket_path, save)

    @wildland_result
    def reset_fs_socket_path(self, save: bool = True):
        """
        Reset the path to the fuse socket to <XDG_RUNTIME_DIR>/wlfuse.sock.

        If environment variable <XDG_RUNTIME_DIR> is not defined <base_dir> is used.
        @param save: if true, save the change to the config file.
        """
        self._reset_param('fs-socket-path', save)

    @wildland_result
    def get_sync_socket_path(self):
        """
        Get the path to the sync socket.
        """
        return self._get_param('sync-socket-path')

    @wildland_result
    def set_sync_socket_path(self, sync_socket_path: str, save: bool = True):
        """
        Set the path to the sync socket.

        @param sync_socket_path: path to the socket
        @param save: if true, save the change to the config file.
        """
        self._set_absolute_path('sync-socket-path', sync_socket_path, save)

    @wildland_result
    def reset_sync_socket_path(self, save: bool = True):
        """
        Reset the path to the fuse socket to <XDG_RUNTIME_DIR>/wlfuse.sock.

        If environment variable <XDG_RUNTIME_DIR> is not defined <base_dir> is used.
        @param save: if true, save the change to the config file.
        """
        self._reset_param('sync-socket-path', save)

    @wildland_result
    def is_alt_bridge_separator(self):
        """
        If true '\uFF1A' will be used as bridge separator instead of ':'.
        """
        return self._get_param('alt-bridge-separator')

    @wildland_result
    def set_alt_bridge_separator(self, alt_bridge_separator: bool, save: bool = True):
        """
        If true '\uFF1A' will be used as bridge separator instead of ':'.

        @param alt_bridge_separator: flag
        @param save: if true, save the change to the config file.
        """
        self._set_param('alt-bridge-separator', alt_bridge_separator, save)

    @wildland_result
    def is_dummy_sig_context(self):
        """
        If true DummySigContext will be used.

        A DummySigContext requires a dummy signature (of the form "dummy.{owner}"),
        for testing purposes.
        """
        return self._get_param('dummy')

    @wildland_result
    def set_dummy_sig_context(self, dummy: bool, save: bool = True):
        """
        If true DummySigContext will be used.

        A DummySigContext requires a dummy signature (of the form "dummy.{owner}"),
        for testing purposes.

        @param dummy: flag
        @param save: if true, save the change to the config file.
        """
        self._set_param('dummy', dummy, save)

    @wildland_result
    def get_default_user(self):
        """
        Get @default user (used to resolve wildland paths).
        """
        return self._get_param('@default')

    @wildland_result
    def set_default_user(self, user_key_fingerprint: str, save: bool = True):
        """
        Set @default user (used to resolve wildland paths).

        @param user_key_fingerprint: fingerprint of user key
        @param save: if true, save the change to the config file.
        """
        self._set_param('@default', user_key_fingerprint, save)

    @wildland_result
    def get_default_owner(self):
        """
        Get @default-owner user (used to resolve wildland paths).
        """
        return self._get_param('@default-owner')

    @wildland_result
    def set_default_owner(self, user_key_fingerprint: str, save: bool = True):
        """
        Set @default-owner user (used to resolve wildland paths).

        @param user_key_fingerprint: fingerprint of user key
        @param save: if true, save the change to the config file.
        """
        self._set_param('@default-owner', user_key_fingerprint, save)

    @wildland_result
    def get_alias(self, alias: str):
        """
        Get alias.

        @param alias: alias, @ at the beginning is ignored
        """
        if alias[0] == '@':
            alias = alias[1:]
        return self.config.aliases[alias]

    @wildland_result
    def set_alias(self, alias: str, user_key_fingerprint: str, save: bool = True):
        """
        Set alias.

        @param alias: alias, @ at the beginning is ignored
        @param user_key_fingerprint: fingerprint of user key
        @param save: if true, save the change to the config file.
        """
        file_aliases = self.config.get('aliases')
        aliases = file_aliases.copy()
        if alias[0] != '@':
            alias = '@' + alias
        aliases[alias] = user_key_fingerprint
        self._set_param('aliases', aliases, save)

    def _remove_values(self,
                       param: str, *values: str,
                       error_code: int = -1,
                       error_description: str = "Incorrect values",
                       is_recoverable: bool = True,
                       offender_type=None,
                       offender_id=None,
                       diagnostic_info="",
                       save: bool = True
                       ):
        file_values = self.config.get(param).copy()
        incorrect_values = list(set(values) - set(file_values))
        wlr = WildlandResult()
        if incorrect_values:
            wlr.success = False
            error = WLError(error_code=error_code,
                            error_description=error_description + f": {incorrect_values}",
                            is_recoverable=is_recoverable,
                            offender_type=offender_type,
                            offender_id=offender_id,
                            diagnostic_info=diagnostic_info)
            wlr.errors.append(error)
        else:
            if isinstance(file_values, dict):
                for value in values:
                    file_values.pop(value)
            elif isinstance(file_values, list):
                file_values = list(set(file_values) - set(values))
            else:
                raise ValueError()
            self._set_param(param, file_values, save)
        return wlr

    @wildland_result
    def remove_aliases(self, *aliases: str, save: bool = True):
        """
        Set @default-owner user (used to resolve wildland paths).

        @param aliases: aliases, @ at the beginning is ignored
        @param save: if true, save the change to the config file.
        """
        full_aliases = ('@' + alias if alias[0] != '@' else alias for alias in aliases)
        return self._remove_values(
            'aliases',
            *full_aliases,
            error_description="Following aliases do not exist",
            save=save
        )

    @wildland_result
    def reset_aliases(self, save: bool = True):
        """
        Remove all aliases except standard ones.

        @param save: if true, save the change to the config file.
        """
        self._reset_param('aliases', save)

    @wildland_result
    def get_local_hostname(self):
        """
        Get local hostname.
        """
        return self._get_param('local-hostname')

    @wildland_result
    def set_local_hostname(self, local_hostname: str, save: bool = True):
        """
        Set local hostname.

        @param local_hostname: hostname
        @param save: if true, save the change to the config file.
        """
        self._set_param('local-hostname', local_hostname, save)

    @wildland_result
    def reset_local_hostname(self, save: bool = True):
        """
        Reset local hostname to 'localhost'.

        @param save: if true, save the change to the config file.
        """
        self._reset_param('local-hostname', save)

    @wildland_result
    def get_local_owners(self):
        """
        Get local owners.
        """
        return self._get_param('local-owners')

    @wildland_result
    def is_local_owner(self, user_key_fingerprint: str):
        """
        Check if user (given by fingerprints of key) is local owner.

        @param user_key_fingerprint: fingerprints of user key
        """
        return user_key_fingerprint in self.config.get('local-owners')

    @wildland_result
    def set_local_owners(self, *user_key_fingerprints: str, save: bool = True):
        """
        Set list of local owners, i.e., owners allowed to access local storages.

        @param user_key_fingerprints: fingerprints of user key
        @param save: if true, save the change to the config file.
        """
        self._set_param('local-owners', list(user_key_fingerprints), save)

    @wildland_result
    def reset_local_owners(self, save: bool = True):
        """
        Remove all local owners from config.

        @param save: if true, save the change to the config file.
        """
        self._reset_param('local-owners', save)

    @wildland_result
    def add_local_owners(self, *user_key_fingerprints: str, save: bool = True):
        """
        Add user_key_fingerprints to local owners.

        @param user_key_fingerprints: fingerprints of user key
        @param save: if true, save the change to the config file.
        """
        file_local_owners = self.config.get('local-owners')
        extended_local_owners = list(user_key_fingerprints) + file_local_owners
        self._set_param('local-owners', extended_local_owners, save)

    @wildland_result
    def remove_local_owners(self, *user_key_fingerprints: str, save: bool = True):
        """
        Remove user_key_fingerprints from local owners.

        @param user_key_fingerprints: fingerprints of user key
        @param save: if true, save the change to the config file.
        """
        return self._remove_values(
            'local-owners',
            *user_key_fingerprints,
            error_description="Following fingerprints are not fingerprints of local owners",
            save=save
        )

    @wildland_result
    def get_default_containers(self):
        """
        Get list of default containers.
        """
        return self._get_param('default-containers')

    @wildland_result
    def is_default_container(self, container_name: str):
        """
        Check if container (given by name) is default container,
        i.e., is mounted at wildland statup.

        @param container_name: fingerprints of user key
        """
        return container_name in self.config.get('default-containers')

    @wildland_result
    def set_default_containers(self, *container_names: str, save: bool = True):
        """
        Set list of default containers, i.e., containers to be mounted at startup.

        @param container_names: container names
        @param save: if true, save the change to the config file.
        """
        self._set_param('default-containers', list(container_names), save)

    @wildland_result
    def reset_default_containers(self, save: bool = True):
        """
        Remove all container_names from default containers.

        @param save: if true, save the change to the config file.
        """
        self._reset_param('default-containers', save)

    @wildland_result
    def add_default_containers(self, *container_names: str, save: bool = True):
        """
        Add container_names to default containers.

        @param container_names: container names
        @param save: if true, save the change to the config file.
        """
        file_containers_names = self.config.get('default-containers')
        extended_container_names = list(container_names) + file_containers_names
        self._set_param('default-containers', extended_container_names, save)

    @wildland_result
    def remove_default_containers(self, *container_names: str, save: bool = True):
        """
        Remove container_names from default containers.

        @param container_names: container names
        @param save: if true, save the change to the config file.
        """
        return self._remove_values(
            'default-containers',
            *container_names,
            error_description="Container names are not name of default containers",
            save=save
        )

    @wildland_result
    def get_default_remote_for_container(self, container_uuid: str):
        """
        Get a default remote storage (backend_id) for
        the container (given by container uuid).
        """
        return self.config.get('default-remote-for-container')[container_uuid]

    @wildland_result
    def set_default_remote_for_container(
        self, container_uuid: str, storage_backend_id: str, save: bool = True
    ):
        """
        Set a default remote storage (given by backend_id) for
        the container (given by container uuid).

        @param container_uuid: uuid of a container
        @param storage_backend_id: backend id of a remote storage
        @param save: if true, save the change to the config file.
        @return:
        """
        file_remotes = self.config.get('default-remote-for-container')
        remotes = file_remotes.copy()  # use a copy to avoid modifying the original dict
        remotes[container_uuid] = storage_backend_id
        config_update = self.__get_update_method(save)
        config_update({'default-remote-for-container': remotes})

    @wildland_result
    def remove_default_remote_for_container(self, *container_uuids: str, save: bool = True):
        """
        Remove default remote storage for the container.

        @param container_uuids: uuid's of a container
        @param save: if true, save the change to the config file.
        """
        return self._remove_values(
            'default-remote-for-container',
            *container_uuids,
            error_description="Following containers do not have default remote storage",
            save=save
        )

    @wildland_result
    def reset_default_remotes(self, save: bool = True):
        """
        Remove all storages from default remotes.

        @param save: if true, save the change to the config file.
        """
        default_value = self.config.default_fields['default-remote-for-container']
        config_update = self.__get_update_method(save)
        config_update({'default-remote-for-container': default_value})

    @wildland_result
    def get_default_cache_template(self):
        """
        Get the specified storage template as default for container cache storages.
        """
        return self._get_param('default-cache-template')

    @wildland_result
    def set_default_cache_template(self, template_name: str, save: bool = True):
        """
        Set the storage template as default for container cache storages.

        @param template_name: template name
        @param save: if true, save the change to the config file.
        """
        self._set_param('default-cache-template', template_name, save)

    @wildland_result
    def reset_default_cache_template(self, save: bool = True):
        """
        Set the storage template as default for container cache storages.

        @param save: if true, save the change to the config file.
        """
        self._reset_param('default-cache-template', save)
