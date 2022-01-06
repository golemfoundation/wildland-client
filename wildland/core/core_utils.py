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
"""
Set of convenience utils for WLCore implementations
"""
from copy import deepcopy
from typing import Optional
from pathlib import PurePosixPath

from wildland.exc import WildlandError
from ..client import Client
from ..user import User
from ..container import Container
from ..bridge import Bridge
from ..storage import Storage
from ..manifest.manifest import Manifest
from ..wildland_object.wildland_object import WildlandObject, PublishableWildlandObject
from .wildland_objects_api import WLUser, WLBridge, WLStorage, WLContainer, WLObjectType, WLObject


def get_object_id(obj: WildlandObject):
    """
    Get WLObjectID
    """
    if isinstance(obj, User):
        return f'{obj.owner}:'
    if isinstance(obj, Container):
        return str(obj.uuid_path)
    if isinstance(obj, Bridge):
        return str(obj.paths[0])  # TODO
    if isinstance(obj, Storage):
        return str(obj.get_unique_publish_id())  # TODO
    return None


def user_to_wluser(user: User, client: Client) -> WLUser:
    """
    Convert User to WLUser
    """
    # TODO: optimize for possible lazy loading of catalog manifests
    wl_user = WLUser(
        owner=user.owner,
        id=get_object_id(user),
        private_key_available=client.session.sig.is_private_key_available(user.owner),
        pubkeys=deepcopy(user.pubkeys),
        paths=[str(p) for p in user.paths],
        manifest_catalog_description=list(user.get_catalog_descriptions()),
        # manifest_catalog_ids=[container.uuid_path for container in user.load_catalog(False)],
    )
    # TODO: currently loading user's catalog messes up their catalog descriptions, which is not
    # ideal, but it's an old bug, not introduced by WLCore
    return wl_user


def container_to_wlcontainer( container: Container) -> WLContainer:
    """
    Convert Container to WLContainer
    """
    wl_container = WLContainer(
        owner=container.owner,
        id=get_object_id(container),
        paths=[str(p) for p in container.paths],
        title=container.title,
        categories=[str(c) for c in container.categories],
        access_ids=[],  # TODO
        storage_ids=[],  # TODO
        storage_description=[],  # TODO
    )
    return wl_container


def bridge_to_wl_bridge(bridge: Bridge) -> WLBridge:
    """
    Convert Bridge to WLBridge
    """
    wl_bridge = WLBridge(
        owner=bridge.owner,
        id=get_object_id(bridge),
        user_pubkey=bridge.user_pubkey,
        user_id=bridge.user_id,
        user_location_description="",  # TODO
        paths=[str(p) for p in bridge.paths],
    )
    return wl_bridge


def storage_to_wl_storage(storage: Storage) -> WLStorage:
    """
    Convert Storage to WLStorage
    """
    wl_storage = WLStorage(
        owner=storage.owner,
        id=get_object_id(storage),
        storage_type=storage.storage_type,
        container="",  # TODO
        trusted=storage.trusted,
        primary=storage.primary,
        access_ids=[],  # TODO
    )
    return wl_storage


def wl_obj_to_wildland_object_type(wl_obj: WLObjectType) -> Optional[WildlandObject.Type]:
    """Convert WLObjectType variable to WildlandObject.Type"""
    try:
        return WildlandObject.Type(wl_obj.value)
    except KeyError:
        return None


def check_object_existence(obj: WildlandObject, client: Client):
    """
    Check if a given object already exists in Client's instance.
    """
    known_id = get_object_id(obj)
    for existing_obj in client.load_all(obj.type):
        if get_object_id(existing_obj) == known_id:
            return True
    return False


def wildland_object_to_wl_object(obj: WildlandObject, client: Client) -> WLObject:
    """
    Convert a WildlandObject to Core API's WLObject
    """
    if isinstance(obj, User):
        return user_to_wluser(obj, client)
    if isinstance(obj, Container):
        return container_to_wlcontainer(obj)
    if isinstance(obj, Bridge):
        return bridge_to_wl_bridge(obj)
    if isinstance(obj, Storage):
        return storage_to_wl_storage(obj)
    raise ValueError


def import_manifest(client: Client, manifest: Manifest,
                    name: Optional[str] = None, overwrite: bool = False):
    """
    Import a provided manifest under provided name.
    """
    wildland_object: WildlandObject = WildlandObject.from_manifest(manifest, client)
    import_type = wildland_object.type

    if import_type not in [WildlandObject.Type.USER, WildlandObject.Type.BRIDGE]:
        raise WildlandError('Can import only user or bridge manifests')

    assert isinstance(wildland_object, PublishableWildlandObject)

    if not name:
        name = '_'.join(wildland_object.get_primary_publish_path().parts)
        paths = getattr(wildland_object, 'paths')
        if paths:
            if len(paths) > 1:
                first_path: PurePosixPath = paths[1]
                name = first_path.stem

    # do not import existing object, unless overwrite=True
    file_path = client.new_path(wildland_object.type, name)

    for obj in client.load_all(import_type):
        if obj.get_unique_publish_id() == wildland_object.get_unique_publish_id():
            if not overwrite:
                raise FileExistsError('Manifest already exists')
            file_path = obj.local_path
            break

    file_path.write_bytes(manifest.to_bytes())


def remove_suffix(s: str, suffix: str) -> str:
    """Remove string suffix"""
    if suffix and s.endswith(suffix):
        return s[:-len(suffix)]
    return s
