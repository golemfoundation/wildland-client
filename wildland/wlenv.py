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
from typing import Optional, Union, List, Tuple
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

    def reload(self, base_dir: Optional[str] = None) -> WildlandResult:
        """
        Reload configuration from config.yaml file.

        @param base_dir: Path to directory with configuration file: <base_dir>/config.yaml
        """
        return self.__reload(base_dir)

    @wildland_result()
    def __reload(self, base_dir: Optional[str] = None):
        base_dir = base_dir or self.base_dir
        self.config = self.load_config(base_dir)

    def reset(self, save: bool = False) -> WildlandResult:
        """
        Set default values for configuration.

        @param save: if true, save the change to the config file.
        """
        return self.__reset(save)

    @wildland_result()
    def __reset(self, save: bool = False):
        if save:
            self.config.override_fields = {}
            self.config.update_and_save({})
        else:
            self.config.override_fields = self.config.default_fields.copy()

    def get_user_dir(self) -> Tuple[WildlandResult, Optional[str]]:
        """
        Get the path to the user manifests directory.
        """
        return self._get_param('user-dir')

    def set_user_dir(self, user_dir: str, save: bool = True) -> WildlandResult:
        """
        Set the path to the user manifests directory.

        @param user_dir: path to the directory
        @param save: if true, save the change to the config file.
        """
        return self._set_absolute_path('user-dir', user_dir, save)

    def reset_user_dir(self, save: bool = True) -> WildlandResult:
        """
        Reset the path to the user manifests directory to <base_dir>/users.

        @param save: if true, save the change to the config file.
        """
        return self._reset_param('user-dir', save)

    def get_storage_dir(self) -> Tuple[WildlandResult, Optional[str]]:
        """
        Get the path to the storage manifests directory.
        """
        return self._get_param('storage-dir')

    def set_storage_dir(self, storage_dir: str, save: bool = True) -> WildlandResult:
        """
        Set the path to the storage manifests directory.

        @param storage_dir: path to the directory
        @param save: if true, save the change to the config file.
        """
        return self._set_absolute_path('storage-dir', storage_dir, save)

    def reset_storage_dir(self, save: bool = True) -> WildlandResult:
        """
        Reset the path to the storage manifests directory to <base_dir>/storage.

        @param save: if true, save the change to the config file.
        """
        return self._reset_param('storage-dir', save)

    def get_cache_dir(self) -> Tuple[WildlandResult, Optional[str]]:
        """
        Get the path for the wildland cache directory.
        """
        return self._get_param('cache-dir')

    def set_cache_dir(self, cache_dir: str, save: bool = True) -> WildlandResult:
        """
        Set the path for the wildland cache directory.

        @param cache_dir: path to the directory
        @param save: if true, save the change to the config file.
        """
        return self._set_absolute_path('cache-dir', cache_dir, save)

    def reset_cache_dir(self, save: bool = True) -> WildlandResult:
        """
        Reset the path for the wildland cache directory to <base_dir>/cache.

        @param save: if true, save the change to the config file.
        """
        return self._reset_param('cache-dir', save)

    def get_container_dir(self) -> Tuple[WildlandResult, Optional[str]]:
        """
        Get the path to the container manifests directory.
        """
        return self._get_param('container-dir')

    def set_container_dir(self, container_dir: str, save: bool = True) -> WildlandResult:
        """
        Set the path to the container manifests directory.

        @param container_dir: path to the directory
        @param save: if true, save the change to the config file.
        """
        return self._set_absolute_path('container-dir', container_dir, save)

    def reset_container_dir(self, save: bool = True) -> WildlandResult:
        """
        Reset the path to the container manifests directory to <base_dir>/containers.

        @param save: if true, save the change to the config file.
        """
        return self._reset_param('container-dir', save)

    def get_bridge_dir(self) -> Tuple[WildlandResult, Optional[str]]:
        """
        Get the path to the bridge manifests directory.
        """
        return self._get_param('bridge-dir')

    def set_bridge_dir(self, bridge_dir: str, save: bool = True) -> WildlandResult:
        """
        Set the path to the bridge manifests directory.

        @param bridge_dir: path to the directory
        @param save: if true, save the change to the config file.
        """
        return self._set_absolute_path('bridge-dir', bridge_dir, save)

    def reset_bridge_dir(self, save: bool = True) -> WildlandResult:
        """
        Reset the path to the bridge manifests directory to <base_dir>/bridges.

        @param save: if true, save the change to the config file.
        """
        return self._reset_param('bridge-dir', save)

    def get_key_dir(self) -> Tuple[WildlandResult, Optional[str]]:
        """
        Get the path to the key directory.
        """
        return self._get_param('key-dir')

    def set_key_dir(self, key_dir: str, save: bool = True) -> WildlandResult:
        """
        Set the path to the key directory.

        @param key_dir: path to the directory
        @param save: if true, save the change to the config file.
        """
        return self._set_absolute_path('key-dir', key_dir, save)

    def reset_key_dir(self, save: bool = True) -> WildlandResult:
        """
        Reset the path to the key directory to <base_dir>/keys.

        @param save: if true, save the change to the config file.
        """
        return self._reset_param('key-dir', save)

    def get_mount_dir(self) -> Tuple[WildlandResult, Optional[str]]:
        """
        Get the path where wildland will be mounted.
        """
        return self._get_param('mount-dir')

    def set_mount_dir(self, mount_dir: str, save: bool = True) -> WildlandResult:
        """
        Set the path where wildland will be mounted.

        @param mount_dir: path to the directory
        @param save: if true, save the change to the config file.
        """
        return self._set_absolute_path('mount-dir', mount_dir, save)

    def reset_mount_dir(self, save: bool = True) -> WildlandResult:
        """
        Reset the path where wildland will be mounted to <home_dir>/wildland.

        @param save: if true, save the change to the config file.
        """
        return self._reset_param('mount-dir', save)

    def get_template_dir(self) -> Tuple[WildlandResult, Optional[str]]:
        """
        Get the path to the templates directory.
        """
        return self._get_param('template-dir')

    def set_template_dir(self, template_dir: str, save: bool = True) -> WildlandResult:
        """
        Set the path to the templates directory.

        @param template_dir: path to the directory
        @param save: if true, save the change to the config file.
        """
        return self._set_absolute_path('template-dir', template_dir, save)

    def reset_template_dir(self, save: bool = True) -> WildlandResult:
        """
        Reset the path to the template directory to <base_dir>/templates.

        @param save: if true, save the change to the config file.
        """
        return self._reset_param('template-dir', save)

    def get_fs_socket_path(self) -> Tuple[WildlandResult, Optional[str]]:
        """
        Get the path to the fuse socket.
        """
        return self._get_param('fs-socket-path')

    def set_fs_socket_path(self, fs_socket_path: str, save: bool = True) -> WildlandResult:
        """
        Set the path to the fuse socket.

        @param fs_socket_path: path to the socket
        @param save: if true, save the change to the config file.
        """
        return self._set_absolute_path('fs-socket-path', fs_socket_path, save)

    def reset_fs_socket_path(self, save: bool = True) -> WildlandResult:
        """
        Reset the path to the fuse socket to <XDG_RUNTIME_DIR>/wlfuse.sock.

        If environment variable <XDG_RUNTIME_DIR> is not defined <base_dir> is used.
        @param save: if true, save the change to the config file.
        """
        return self._reset_param('fs-socket-path', save)

    def get_sync_socket_path(self) -> Tuple[WildlandResult, Optional[str]]:
        """
        Get the path to the sync socket.
        """
        return self._get_param('sync-socket-path')

    def set_sync_socket_path(self, sync_socket_path: str, save: bool = True) -> WildlandResult:
        """
        Set the path to the sync socket.

        @param sync_socket_path: path to the socket
        @param save: if true, save the change to the config file.
        """
        return self._set_absolute_path('sync-socket-path', sync_socket_path, save)

    def reset_sync_socket_path(self, save: bool = True) -> WildlandResult:
        """
        Reset the path to the fuse socket to <XDG_RUNTIME_DIR>/wlfuse.sock.

        If environment variable <XDG_RUNTIME_DIR> is not defined <base_dir> is used.
        @param save: if true, save the change to the config file.
        """
        return self._reset_param('sync-socket-path', save)

    def is_alt_bridge_separator(self) -> Tuple[WildlandResult, Optional[bool]]:
        """
        If true '\uFF1A' will be used as bridge separator instead of ':'.
        """
        return self._get_param('alt-bridge-separator')

    def set_alt_bridge_separator(self, alt_bridge_separator: bool,
                                 save: bool = True) -> WildlandResult:
        """
        If true '\uFF1A' will be used as bridge separator instead of ':'.

        @param alt_bridge_separator: flag
        @param save: if true, save the change to the config file.
        """
        return self._set_param('alt-bridge-separator', alt_bridge_separator, save)

    def is_dummy_sig_context(self) -> Tuple[WildlandResult, Optional[bool]]:
        """
        If true DummySigContext will be used.

        A DummySigContext requires a dummy signature (of the form "dummy.{owner}"),
        for testing purposes.
        """
        return self._get_param('dummy')

    def set_dummy_sig_context(self, dummy: bool, save: bool = True) -> WildlandResult:
        """
        If true DummySigContext will be used.

        A DummySigContext requires a dummy signature (of the form "dummy.{owner}"),
        for testing purposes.

        @param dummy: flag
        @param save: if true, save the change to the config file.
        """
        return self._set_param('dummy', dummy, save)

    def get_default_user(self, use_override: bool = True) -> Tuple[WildlandResult, Optional[str]]:
        """
        Get @default user (used to resolve wildland paths). If use_override is False, any
        overriden start values will be ignored.
        """
        return self._get_param('@default', use_override=use_override)

    def set_default_user(self, user_key_fingerprint: str, save: bool = True) -> WildlandResult:
        """
        Set @default user (used to resolve wildland paths).

        @param user_key_fingerprint: fingerprint of user key
        @param save: if true, save the change to the config file.
        """
        return self._set_param('@default', user_key_fingerprint, save)

    def get_default_owner(self) -> Tuple[WildlandResult, Optional[str]]:
        """
        Get @default-owner user (used to resolve wildland paths).
        """
        return self._get_param('@default-owner')

    def set_default_owner(self, user_key_fingerprint: str, save: bool = True) -> WildlandResult:
        """
        Set @default-owner user (used to resolve wildland paths).

        @param user_key_fingerprint: fingerprint of user key
        @param save: if true, save the change to the config file.
        """
        return self._set_param('@default-owner', user_key_fingerprint, save)

    def get_alias(self, alias: str) -> Tuple[WildlandResult, Optional[str]]:
        """
        Get alias.

        @param alias: alias, @ at the beginning is ignored
        """
        wlr, new_alias = self.__ignore_at(alias)
        if not wlr.success:
            return wlr, new_alias
        return wildland_result(default_output=None)(
            lambda a: self.config.aliases[a])(new_alias)

    @staticmethod
    @wildland_result(default_output=None)
    def __ignore_at(alias: str):
        if alias[0] == '@':
            alias = alias[1:]
        return alias

    def set_alias(self, alias: str, user_key_fingerprint: str, save: bool = True) -> WildlandResult:
        """
        Set alias.

        @param alias: alias, @ at the beginning is ignored
        @param user_key_fingerprint: fingerprint of user key
        @param save: if true, save the change to the config file.
        """
        wlr, new_alias = self.__add_at(alias)
        if not wlr.success:
            return wlr
        return self._set_param_key_value('aliases', new_alias, user_key_fingerprint, save)

    @staticmethod
    @wildland_result(default_output=None)
    def __add_at(alias: str):
        if alias[0] != '@':
            alias = '@' + alias
        return alias

    def remove_aliases(self, *aliases: str, save: bool = True) -> WildlandResult:
        """
        Set @default-owner user (used to resolve wildland paths).

        @param aliases: aliases, @ at the beginning is ignored
        @param save: if true, save the change to the config file.
        """
        wlr, full_aliases = wildland_result(default_output=[])(
            lambda als: ('@' + alias if alias[0] != '@' else alias for alias in als))(
            tuple(aliases))
        if not wlr.success:
            return wlr
        return self._remove_values(
            'aliases',
            *full_aliases,
            error_description="Following aliases do not exist",
            save=save
        )

    def reset_aliases(self, save: bool = True) -> WildlandResult:
        """
        Remove all aliases except standard ones.

        @param save: if true, save the change to the config file.
        """
        return self._reset_param('aliases', save)

    def get_local_hostname(self) -> Tuple[WildlandResult, Optional[str]]:
        """
        Get local hostname.
        """
        return self._get_param('local-hostname')

    def set_local_hostname(self, local_hostname: str, save: bool = True) -> WildlandResult:
        """
        Set local hostname.

        @param local_hostname: hostname
        @param save: if true, save the change to the config file.
        """
        return self._set_param('local-hostname', local_hostname, save)

    def reset_local_hostname(self, save: bool = True) -> WildlandResult:
        """
        Reset local hostname to 'localhost'.

        @param save: if true, save the change to the config file.
        """
        return self._reset_param('local-hostname', save)

    def get_local_owners(self) -> Tuple[WildlandResult, List[str]]:
        """
        Get local owners.
        """
        wlr, result = self._get_param('local-owners')
        if result is None:
            return wlr, []
        return wlr, result

    def is_local_owner(self, user_key_fingerprint: str) -> Tuple[WildlandResult, Optional[bool]]:
        """
        Check if user (given by fingerprints of key) is local owner.

        @param user_key_fingerprint: fingerprints of user key
        """
        return wildland_result(default_output=None)(
            lambda key: key in self.config.get('local-owners'))(user_key_fingerprint)

    def set_local_owners(self, *user_key_fingerprints: str, save: bool = True) -> WildlandResult:
        """
        Set list of local owners, i.e., owners allowed to access local storages.

        @param user_key_fingerprints: fingerprints of user key
        @param save: if true, save the change to the config file.
        """
        return self._set_param('local-owners', list(user_key_fingerprints), save)

    def reset_local_owners(self, save: bool = True) -> WildlandResult:
        """
        Remove all local owners from config.

        @param save: if true, save the change to the config file.
        """
        return self._reset_param('local-owners', save)

    def add_local_owners(self, *user_key_fingerprints: str, save: bool = True) -> WildlandResult:
        """
        Add user_key_fingerprints to local owners.

        @param user_key_fingerprints: fingerprints of user key
        @param save: if true, save the change to the config file.
        """
        return self._add_values('local-owners', *user_key_fingerprints, save=save)

    def remove_local_owners(self, *user_key_fingerprints: str, save: bool = True) -> WildlandResult:
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

    def get_default_containers(self) -> Tuple[WildlandResult, List[str]]:
        """
        Get list of default containers.
        """
        wlr, result = self._get_param('default-containers')
        if result is None:
            return wlr, []
        return wlr, result

    def is_default_container(self, container_name: str) -> Tuple[WildlandResult, Optional[bool]]:
        """
        Check if container (given by name) is default container,
        i.e., is mounted at wildland statup.

        @param container_name: fingerprints of user key
        """
        return wildland_result(default_output=None)(
            lambda name: name in self.config.get('default-containers'))(container_name)

    def set_default_containers(self, *container_names: str, save: bool = True) -> WildlandResult:
        """
        Set list of default containers, i.e., containers to be mounted at startup.

        @param container_names: container names
        @param save: if true, save the change to the config file.
        """
        return self._set_param('default-containers', list(container_names), save)

    def reset_default_containers(self, save: bool = True) -> WildlandResult:
        """
        Remove all container_names from default containers.

        @param save: if true, save the change to the config file.
        """
        return self._reset_param('default-containers', save)

    def add_default_containers(self, *container_names: str, save: bool = True) -> WildlandResult:
        """
        Add container_names to default containers.

        @param container_names: container names
        @param save: if true, save the change to the config file.
        """
        return self._add_values('default-containers', *container_names, save=save)

    def remove_default_containers(self, *container_names: str, save: bool = True) -> WildlandResult:
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

    def get_default_remote_for_container(self, container_uuid: str) \
            -> Tuple[WildlandResult, Optional[str]]:
        """
        Get a default remote storage (backend_id) for
        the container (given by container uuid).
        """
        return wildland_result(default_output=None)(
            lambda uuid: self.config.get('default-remote-for-container')[uuid])(container_uuid)

    def set_default_remote_for_container(
            self, container_uuid: str, storage_backend_id: str, save: bool = True) \
            -> WildlandResult:
        """
        Set a default remote storage (given by backend_id) for
        the container (given by container uuid).

        @param container_uuid: uuid of a container
        @param storage_backend_id: backend id of a remote storage
        @param save: if true, save the change to the config file.
        @return:
        """
        return self._set_param_key_value(
            'default-remote-for-container', container_uuid, storage_backend_id, save)

    def remove_default_remote_for_container(self, *container_uuids: str, save: bool = True) \
            -> WildlandResult:
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

    def reset_default_remotes(self, save: bool = True) -> WildlandResult:
        """
        Remove all storages from default remotes.

        @param save: if true, save the change to the config file.
        """
        return self._reset_param('default-remote-for-container', save)

    def get_default_cache_template(self) -> Tuple[WildlandResult, Optional[str]]:
        """
        Get the specified storage template as default for container cache storages.
        """
        return self._get_param('default-cache-template')

    def set_default_cache_template(self, template_name: str, save: bool = True) -> WildlandResult:
        """
        Set the storage template as default for container cache storages.

        @param template_name: template name
        @param save: if true, save the change to the config file.
        """
        return self._set_param('default-cache-template', template_name, save)

    def reset_default_cache_template(self, save: bool = True):
        """
        Set the storage template as default for container cache storages.

        @param save: if true, save the change to the config file.
        """
        return self._reset_param('default-cache-template', save)

    def __get_update_method(self, save: bool):
        return self.config.update_and_save if save else partial(self.config.override, dummy=False)

    @wildland_result(default_output=None)
    def _get_param(self, param: str, use_override: bool = True):
        result = self.config.get(param, use_override=use_override)
        return result

    @wildland_result()
    def _set_param(self, param: str, value: Union[bool, str, List[str]], save: bool):
        config_update = self.__get_update_method(save)
        config_update({param: value})

    @wildland_result()
    def _set_absolute_path(self, param: str, path: str, save: bool):
        if not Path(path).is_absolute():
            raise ValueError("Given value is not absolute path.")
        config_update = self.__get_update_method(save)
        config_update({param: path})

    @wildland_result()
    def _reset_param(self, param: str, save: bool):
        default_value = self.config.default_fields[param]
        self.config.override({param: default_value})
        if save:
            self.config.remove_key_and_save(param)

    @wildland_result()
    def _add_values(self, param: str, *values: str, save: bool = True):
        file_values = self.config.get(param)
        extended_values = list(values) + file_values
        return self._set_param(param, extended_values, save)

    @wildland_result()
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

    @wildland_result()
    def _set_param_key_value(self, param: str, key: str, value: str, save: bool):
        file_values = self.config.get(param)
        values = file_values.copy()
        values[key] = value
        return self._set_param(param, values, save)
