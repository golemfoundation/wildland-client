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
# pylint: disable=too-many-lines
"""
Wildland core implementation - user-related functions
"""
from typing import List, Tuple, Optional, Callable, Dict, Union
from pathlib import PurePosixPath

import wildland.core.core_utils as utils
from wildland.log import get_logger
from wildland.exc import WildlandError
from wildland.wlpath import WildlandPath
from ..client import Client
from ..user import User
from ..wildland_object.wildland_object import WildlandObject
from .wildland_result import WildlandResult, WLError, wildland_result
from .wildland_core_api import WildlandCoreApi, ModifyMethod
from .wildland_objects_api import WLUser, WLObject
from ..wlenv import WLEnv


logger = get_logger('core')


class WildlandCoreUser(WildlandCoreApi):
    """
    User-related methods of WildlandCore
    """
    def __init__(self, client: Client):
        # info: this is here to stop mypy from complaining about missing params
        self.client = client
        self.env = WLEnv(base_dir=self.client.base_dir)

    def user_get_usages(self, user_id: str) -> Tuple[WildlandResult, List[WLObject]]:
        """
        Get all usages of the given user in the local context, e.g. objects owned by them.
        :param user_id: user's id
        :return: tuple of WildlandResult and list of objects found
        """
        return self.__user_get_usages(user_id)

    @wildland_result(default_output=[])
    def __user_get_usages(self, user_id: str):
        usages: List[WLObject] = []
        result, obj = self.user_get_by_id(user_id)
        if not result.success:
            return result, usages
        assert obj
        for container in self.client.load_all(WildlandObject.Type.CONTAINER):
            if container.owner == obj.owner:
                usages.append(utils.container_to_wlcontainer(container))
        return usages

    # USER METHODS
    def user_get_by_id(self, user_id: str) -> Tuple[WildlandResult, Optional[WLUser]]:
        """
        Get user from specified ID.
        """
        return self.__user_get_by_id(user_id)

    @wildland_result(default_output=None)
    def __user_get_by_id(self, user_id: str):
        user_name = user_id[:-1]
        user_obj = self.client.load_object_from_name(WildlandObject.Type.USER, user_name)
        return utils.user_to_wluser(user_obj, self.client)

    def user_generate_key(self) -> Tuple[WildlandResult, Optional[str], Optional[str]]:
        """
        Generate a new encryption and signing key(s), store them in an appropriate location and
        return key owner id and public key generated.
        """
        result = WildlandResult()
        owner: Optional[str]
        pubkey: Optional[str]
        try:
            owner, pubkey = self.client.session.sig.generate()
        except Exception as ex:
            result.errors.append(WLError.from_exception(ex))
            owner, pubkey = None, None
        return result, owner, pubkey

    def user_remove_key(self, owner: str, force: bool) -> WildlandResult:
        """
        Remove an existing encryption/signing key. If force is False, the key will not be removed
        if there are any users who use it as a secondary encryption key.
        """
        return self.__user_remove_key(owner, force)

    @wildland_result()
    def __user_remove_key(self, owner: str, force: bool):
        result = WildlandResult()
        possible_owners = self.client.session.sig.get_possible_owners(owner)
        if possible_owners != [owner] and not force:
            result.errors.append(
                WLError(701, 'Key used by other users as secondary key and will not be deleted. '
                             'Key should be removed manually. In the future you can use --force to '
                             'force key deletion.', False))
            return result
        self.client.session.sig.remove_key(owner)
        return result

    def user_import_key(self, public_key: bytes, private_key: bytes) -> WildlandResult:
        """
        Import provided public and private key. The keys must follow key format appropriate for
        used SigContext (see documentation)
        :param public_key: bytes with public key
        :param private_key: bytes with private key
        :return: WildlandResult
        """
        raise NotImplementedError

    def user_get_public_key(self, owner: str) -> Tuple[WildlandResult, Optional[str]]:
        """
        Return public key for the provided owner.
        :param owner: owner fingerprint
        :return: Tuple of WildlandResult and, if successful, this user's public key
        """
        return self.__user_get_pubkey(owner)

    @wildland_result(default_output=None)
    def __user_get_pubkey(self, owner):
        _, pubkey = self.client.session.sig.load_key(owner)
        return pubkey

    def user_create(self, name: Optional[str], keys: List[str], paths: List[str]) -> \
            Tuple[WildlandResult, Optional[WLUser]]:
        """
        Create a user and return information about it
        :param name: file name for the newly created file
        :param keys: list of user's public keys, starting with their own key
        :param paths: list of user paths (paths must be absolute paths)
        """
        return self.__user_create(name, keys, paths)

    @wildland_result(default_output=None)
    def __user_create(self, name: Optional[str], keys: List[str], paths: List[str]):
        if not keys:
            result = WildlandResult()
            result.errors.append(WLError(100, "At least one public key must be provided", False))
            return result, None

        members = []
        filtered_additional_keys = []
        own_key = keys[0]

        for k in keys:
            if k == own_key:
                continue
            if WildlandPath.WLPATH_RE.match(k):
                members.append({"user-path": WildlandPath.get_canonical_form(k)})
            else:
                filtered_additional_keys.append(k)

        owner = self.client.session.sig.fingerprint(own_key)
        user = User(
            owner=owner,
            pubkeys=[own_key] + filtered_additional_keys,
            paths=[PurePosixPath(p) for p in paths],
            manifests_catalog=[],
            client=self.client,
            members=members)

        path = self.client.save_new_object(WildlandObject.Type.USER, user, name)
        logger.info('Created: %s', path)

        user.add_user_keys(self.client.session.sig)

        wl_user = utils.user_to_wluser(user, self.client)
        return wl_user

    def user_list(self) -> Tuple[WildlandResult, List[WLUser]]:
        """
        List all known users.
        :return: WildlandResult, List of WLUsers
        """
        result = WildlandResult()
        result_list = []
        try:
            for user in self.client.load_all(WildlandObject.Type.USER):
                result_list.append(utils.user_to_wluser(user, self.client))
        except Exception as ex:
            result.errors.append(WLError.from_exception(ex))
        return result, result_list

    def user_delete(self, user_id: str) -> WildlandResult:
        """
        Delete provided user.
        :param user_id: User ID (in the form of user fingerprint)
        :return: WildlandResult
        """
        return self.__user_delete(user_id)

    @wildland_result(default_output=())
    def __user_delete(self, user_id: str):
        user = self.client.load_object_from_name(WildlandObject.Type.USER, user_id)
        if not user.local_path:
            raise FileNotFoundError('Can only delete a local manifest')
        user.local_path.unlink()

    def user_refresh(self, user_ids: Optional[List[str]] = None,
                     callback: Callable[[str], None] = None) -> WildlandResult:
        """
        Iterates over bridges and fetches each user's file from the URL specified in the bridge
        :param user_ids: Optional list of user_ids to refresh; if None, will refresh all users
            with a bridge present
        :param callback: function to be called before each refreshed user
        :return: WildlandResult
        """
        result = WildlandResult()

        users_to_refresh: Dict[str, Union[dict, str]] = dict()

        for bridge in self.client.get_local_bridges():
            if user_ids is not None \
                    and f'{self.client.session.sig.fingerprint(bridge.user_pubkey)}' \
                    not in user_ids:
                continue
            if bridge.owner in users_to_refresh:
                # this is a heuristic to avoid downloading the same user multiple times, but
                # preferring link object to bare URL
                if isinstance(users_to_refresh[bridge.owner], str) and \
                        isinstance(bridge.user_location, dict):
                    users_to_refresh[bridge.owner] = bridge.user_location
            else:
                users_to_refresh[bridge.owner] = bridge.user_location

        for owner, location in users_to_refresh.items():
            try:
                wl_object = self.client.load_object_from_url_or_dict(None, location, owner)
                if isinstance(location, str):
                    path = location
                else:
                    path = location.get('file', '')
                name = path.split('/')[-1]
                utils.import_manifest(self.client, wl_object.manifest, name=name, overwrite=True)
            except WildlandError as ex:
                result.errors.append(WLError.from_exception(ex))

        return result

    def user_modify(self, user_id: str, manifest_field: str, operation: ModifyMethod,
                    modify_data: List[str]) -> WildlandResult:
        """
        Modify user manifest
        :param user_id: fingerprint of the user to be modified
        :param manifest_field: field to modify; supports the following:
            - paths
            - manifest-catalog
            - pubkeys
        :param operation: operation to perform on field ('add' or 'delete')
        :param modify_data: list of values to be added/removed
        :return: WildlandResult
        """
        raise NotImplementedError

    def user_publish(self, user_id) -> WildlandResult:
        """
        Publish the given user.
        :param user_id: fingerprint of the user to be published
        :return: WildlandResult
        """
        raise NotImplementedError

    def user_unpublish(self, user_id) -> WildlandResult:
        """
        Unpublish the given user.
        :param user_id: fingerprint of the user to be unpublished
        :return: WildlandResult
        """
        raise NotImplementedError
