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
API for Wildland Core Objects
"""
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Optional


class WLObjectType(Enum):
    """
    Types of Wildland object. Corresponds to internal WildlandObject.Type
    """
    USER = 'user'
    BRIDGE = 'bridge'
    CONTAINER = 'container'
    STORAGE = 'storage'
    FILE = 'file'
    TEMPLATE = 'template'


@dataclass
class WLObject:
    """
    Generalized Wildland object
    """
    #: object owner; provided as public key fingerprint
    owner: str
    #: Wildland object id, syntax based on WL paths:
    #: 0xaaa:[/.uuid/000-000-000:/.uuid/000-000-000]
    #: USERS: userid:
    #: BRIDGES: ownerid:uuid
    #: CONTAINERS: ownerid:uuid
    #: STORAGES: ownerid:container_uuid:uuid
    id: str

    def toJSON(self):
        """
        Used for serializing, e.g. into other languages
        """

    @classmethod
    def fromJSON(cls):
        """
        Used for deserializing, e.g. from other languages
        """

# TODO: add is_published api method
    @property
    def published(self):
        """
        Whether given object is published.
        :return: bool
        """
        return False


@dataclass
class WLUser(WLObject):
    """
    Wildland user
    """
    #: is user's private key available
    private_key_available: bool
    #: list of user's public keys
    pubkeys: List[str] = field(default_factory=list)
    #: list of user's paths
    paths: List[str] = field(default_factory=list)
    #: ids of containers ids in user's manifest catalog
    manifest_catalog_ids: List[str] = field(default_factory=list)
    #: human-readable description of manifest_catalog contents; should be in the same order as
    #: manifest_catalog_ids
    manifest_catalog_description: List[str] = field(default_factory=list)


@dataclass
class WLContainer(WLObject):
    """
    Wildland container
    """
    #: list of container paths
    paths: List[str] = field(default_factory=list)
    #: container title
    title: Optional[str] = None
    #: list of container categories
    categories: List[str] = field(default_factory=list)
    #: list of ids of or wl paths to users that have access to this container
    access_ids: List[str] = field(default_factory=list)
    #: list of ids of storages in this container
    storage_ids: List[str] = field(default_factory=list)
    #: human-readable list of storages of this container, in the same order as storage_ids
    storage_description: List[str] = field(default_factory=list)


@dataclass
class WLStorage(WLObject):
    """
    Wildland storage
    """
    #: storage backend type
    storage_type: str
    #: id of the container owning this storage
    container: str  # container id
    #: is this storage trusted
    trusted: bool
    #: is this a primary storage of the container
    primary: bool
    #: list of ids of or wl paths to users that have access to this manifest
    access_ids: List[str] = field(default_factory=list)


@dataclass
class WLBridge(WLObject):
    """
    Wildland bridge
    """
    #: public key of user this bridge is pointing to
    user_pubkey: str
    #: id of user this bridge is pointing to
    user_id: str
    #: human-readable description of user location
    user_location_description: str
    #: bridge paths
    paths: List[str] = field(default_factory=list)


@dataclass
class WLStorageBackend:
    """
    Wildland storage backend type
    """
    #: name of the storage backend
    name: str
    #: human-readable description of the storage backend
    description: str
    #: list of fields this backend supports
    supported_fields: List[str]
    #: description of fields this backend supports; must be in the same order as supported_fields
    field_descriptions: List[str]
    #: subset of supported_fields that is required for the backend to work
    required_fields: List[str] = field(default_factory=list)


@dataclass
class WLTemplateFile:
    """
    Wildland template file
    """
    #: template file name
    name: str
    #: list of templates within the file
    templates: List[str] = field(default_factory=list)
    #: human-readable descriptions of templates within the file
    template_descriptions: List[str] = field(default_factory=list)
