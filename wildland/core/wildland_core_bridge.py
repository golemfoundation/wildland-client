# Wildland Project
#
# Copyright (C) 2022 Golem Foundation
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
# pylint: disable=too-many-lines
"""
Wildland core implementation - bridge-related functions
"""
from typing import List, Tuple, Optional
from pathlib import PurePosixPath, Path
from copy import deepcopy

import wildland.core.core_utils as utils
from wildland.log import get_logger
from .wildland_core_api import WildlandCoreApi, ModifyMethod
from .wildland_objects_api import WLBridge
from .wildland_result import WildlandResult, WLError, wildland_result
from ..bridge import Bridge
from ..client import Client
from ..link import Link
from ..wildland_object.wildland_object import WildlandObject
from ..manifest.manifest import Manifest
from ..wlpath import WildlandPath, WILDLAND_URL_PREFIX
from ..wlenv import WLEnv

logger = get_logger('core-bridge')


class WildlandCoreBridge(WildlandCoreApi):
    """
    Bridge-related methods of WildlandCore
    """
    def __init__(self, client: Client):
        # info: this is here to stop mypy from complaining about missing params
        self.client = client
        self.env = WLEnv(base_dir=self.client.base_dir)

    def bridge_create(self, paths: Optional[List[str]], owner: Optional[str] = None,
                      target_user: Optional[str] = None, user_url: Optional[str] = None,
                      name: Optional[str] = None) -> \
            Tuple[WildlandResult, Optional[WLBridge]]:
        """
        Create a new bridge. At least one from target_user, user_url must be provided.
        :param paths: paths for user in owner namespace (if None, will be taken from user manifest)
        :param owner: user_id for the owner of the created bridge
        :param target_user: user_id to whom the bridge will point. If provided, will be used to
        verify the integrity of the target_user_url
        :param user_url: path to the user manifest (use file:// for local file). If target_user
        is provided, their user manifest will be first located in their manifests catalog, and only
        as a second choice from this url.
        If target_user is skipped, the user manifest from this path is considered trusted.
        :param name: optional name for the newly created bridge. If omitted, will be generated
        automatically
        :return: tuple of WildlandResult and, if successful, the created WLBridge
        """
        return self.__bridge_create(paths, owner, target_user, user_url, name)

    @wildland_result(default_output=None)
    def __bridge_create(self, paths: Optional[List[str]], owner: Optional[str] = None,
                        target_user: Optional[str] = None, user_url: Optional[str] = None,
                        name: Optional[str] = None):

        if not target_user and not user_url:
            raise ValueError('Bridge creation requires at least one of: target user id, target '
                             'user url.')
        if user_url and not self.client.is_url(user_url):
            user_url = self.client.local_url(Path(user_url))
            if not self.client.is_url(user_url):
                raise ValueError('Bridge requires user URL')

        if not owner:
            result, owner = self.env.get_default_owner()
            if not owner:
                raise FileNotFoundError(f'Default owner not found: {result}')

        owner_user = self.client.load_object_from_name(WildlandObject.Type.USER, owner)

        if target_user:
            target_user_object = self.client.load_object_from_name(
                WildlandObject.Type.USER, target_user)
        else:
            assert user_url
            target_user_object = self.client.load_object_from_url(
                WildlandObject.Type.USER, user_url, owner=owner_user.owner,
                expected_owner=target_user)

        try:
            found_manifest = self.client.find_user_manifest_within_catalog(target_user_object)
        except PermissionError:
            found_manifest = None

        if not found_manifest:
            if user_url and not self.client.is_local_url(user_url):
                location = user_url
            elif target_user_object.local_path:
                logger.debug('Cannot find user manifest in manifests catalog. '
                               'Using local file path.')
                location = self.client.local_url(target_user_object.local_path)
            elif user_url:
                location = user_url
            else:
                raise FileNotFoundError('User manifest not found in manifests catalog. '
                                        'Provide explicit url.')
        else:
            storage, file = found_manifest
            file = '/' / file
            location_link = Link(file, client=self.client, storage=storage)
            location = location_link.to_manifest_fields(inline=True)

        fingerprint = self.client.session.sig.fingerprint(target_user_object.primary_pubkey)

        if paths:
            bridge_paths = [PurePosixPath(p) for p in paths]
        else:
            bridge_paths = target_user_object.paths
            logger.debug(
                "Using user's default paths: %s", [str(p) for p in target_user_object.paths])

        bridge = Bridge(
            owner=owner_user.owner,
            user_location=location,
            user_pubkey=target_user_object.primary_pubkey,
            user_id=fingerprint,
            paths=bridge_paths,
            client=self.client
        )

        if not name and bridge_paths:
            # an heuristic for nicer paths
            for path in bridge_paths:
                if 'uuid' not in str(path):
                    name = str(path).lstrip('/').replace('/', '_')
                    break
        path = self.client.save_new_object(WildlandObject.Type.BRIDGE, bridge, name)
        logger.info("Created: %s", path)
        return utils.bridge_to_wl_bridge(bridge)

    def bridge_list(self) -> Tuple[WildlandResult, List[WLBridge]]:
        """
        List all known bridges.
        :return: WildlandResult, List of WLBridges
        """
        result = WildlandResult()
        result_list = []
        try:
            for bridge in self.client.load_all(WildlandObject.Type.BRIDGE):
                result_list.append(utils.bridge_to_wl_bridge(bridge))
        except Exception as ex:
            result.errors.append(WLError.from_exception(ex))
        return result, result_list

    def bridge_delete(self, bridge_id: str) -> WildlandResult:
        """
        Delete provided bridge.
        :param bridge_id: Bridge ID (in the form of user_id:/.uuid/bridge_uuid)
        :return: WildlandResult
        """
        return self.__bridge_delete(bridge_id)

    @wildland_result(default_output=())
    def __bridge_delete(self, bridge_id: str):
        for bridge in self.client.load_all(WildlandObject.Type.BRIDGE):
            if utils.get_object_id(bridge) == bridge_id:
                bridge.local_path.unlink()
                return
        raise FileNotFoundError(f'Cannot find bridge {bridge_id}')

    def bridge_import_from_url(self, path_or_url: str, paths: List[str],
                               object_owner: str, only_first: bool = False,
                               name: Optional[str] = None) -> \
            Tuple[WildlandResult, List[WLBridge]]:
        """
        Import bridge(s) from provided url or path, creating a new bridge(s) with provided owner and
        paths.
        :param path_or_url: WL path or URL
        :param paths: list of paths for resulting bridge manifest; if empty, will use provided
        bridge's paths, scrambled for uniqueness; if WL path to multiple bridges is provided, this
        requires --only-first
        :param object_owner: owner for the newly created bridge
        :param only_first: import only first encountered bridge (ignored in all cases except
            WL container paths)
        :param name: user-friendly name for the imported bridge
        :return: tuple of WildlandResult, list of imported WLBridge(s) (if import was successful
        """

        return self._bridge_import_from_url(path_or_url, paths, object_owner, only_first, name)

    @wildland_result([])
    def _bridge_import_from_url(self, path_or_url: str, paths: List[str],
                                object_owner: str, only_first: bool = False,
                                name: Optional[str] = None):
        bridges = list(self.client.read_bridge_from_url(path_or_url, use_aliases=True))

        if WildlandPath.WLPATH_RE.match(path_or_url):
            name = path_or_url.replace(WILDLAND_URL_PREFIX, '')

        if paths and not only_first and len(bridges) > 1:
            raise ValueError('Cannot import multiple bridges with --path specified.')
        if only_first:
            bridges = [bridges[0]]

        for bridge in bridges:
            assert isinstance(bridge, Bridge)
            self._do_import_bridge(bridge, paths, object_owner, name)
        return bridges

    def bridge_import_from_yaml(self, yaml_data: bytes, paths: List[str],
                                object_owner: str, name: Optional[str] = None) -> \
            Tuple[WildlandResult, Optional[WLBridge]]:
        """
        Import bridge from provided yaml data.
        :param yaml_data: yaml data to be imported
        :param paths: list of paths for resulting bridge manifest; if omitted, will use imported
            user's own paths
        :param object_owner: specify a different-from-default user to be used as the owner of
            created bridge manifests
        :param name: user-friendly name for the imported bridge
        :return: tuple of WildlandResult, imported WLUser (if import was successful
        """

        return self._bridge_import_from_yaml(yaml_data, paths, object_owner, name)

    @wildland_result(default_output=None)
    def _bridge_import_from_yaml(self, yaml_data: bytes, paths: List[str],
                                 object_owner: str, name: Optional[str] = None):
        Manifest.verify_and_load_pubkeys(yaml_data, self.client.session.sig)

        bridge: Bridge = self.client.load_object_from_bytes(
            WildlandObject.Type.BRIDGE, data=yaml_data)

        return self._do_import_bridge(bridge, paths, object_owner, name)

    def _do_import_bridge(self, bridge: Bridge, paths: List[str], owner: str, name: Optional[str])\
            -> WLBridge:
        fingerprint = self.client.session.sig.fingerprint(bridge.user_pubkey)
        posix_paths = [PurePosixPath(p) for p in paths]
        new_bridge = Bridge(
            owner=owner,
            user_location=deepcopy(bridge.user_location),
            user_pubkey=bridge.user_pubkey,
            user_id=fingerprint,
            paths=(posix_paths or
                   Bridge.create_safe_bridge_paths(fingerprint, bridge.paths)),
            client=self.client
        )
        bridge_name = None
        if name:
            bridge_name = name.replace(':', '_').replace('/', '_')
        bridge_path = self.client.save_new_object(
            WildlandObject.Type.BRIDGE, new_bridge, bridge_name, None)
        logger.info('Created: %s', bridge_path)
        wl_bridge = utils.bridge_to_wl_bridge(new_bridge)
        return wl_bridge

    def bridge_modify(self, bridge_id: str, manifest_field: str, operation: ModifyMethod,
                      modify_data: List[str]) -> WildlandResult:
        """
        Modify bridge manifest
        :param bridge_id: id of the bridge to be modified, in the form of user_id:/.uuid/bridge_uuid
        :param manifest_field: field to modify; supports the following:
            - paths
        :param operation: operation to perform on field ('add' or 'delete')
        :param modify_data: list of values to be added/removed
        :return: WildlandResult
        """
        raise NotImplementedError

    def bridge_publish(self, bridge_id) -> WildlandResult:
        """
        Publish the given bridge.
        :param bridge_id: id of the bridge to be published (user_id:/.uuid/bridge_uuid)
        :return: WildlandResult
        """
        raise NotImplementedError

    def bridge_unpublish(self, bridge_id) -> WildlandResult:
        """
        Unpublish the given bridge.
        :param bridge_id: id of the bridge to be unpublished (user_id:/.uuid/bridge_uuid)
        :return: WildlandResult
        """
        raise NotImplementedError
