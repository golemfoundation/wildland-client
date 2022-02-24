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
API for Wildland Core
"""
import abc
from typing import List, Tuple, Optional, Callable, Dict
from enum import Enum
from .wildland_result import WildlandResult
from .wildland_objects_api import WLObject, WLTemplateFile, WLBridge, WLObjectType, WLUser, \
    WLStorageBackend, WLStorage, WLContainer


class ModifyMethod(Enum):
    """
    Possible input values for various object modify methods
    """
    ADD = 'add'
    DELETE = 'delete'
    SET = 'set'


class WildlandCoreApi(metaclass=abc.ABCMeta):
    """
    Wildland Core API
    """
    # All methods must wrap any exceptions in WildlandResult

    # GENERAL METHODS
    @abc.abstractmethod
    def object_info(self, yaml_data: str) -> Tuple[WildlandResult, Optional[WLObject]]:
        """
        This method parses yaml data and returns an appropriate WLObject; to perform any further
        operations the object has to be imported.
        :param yaml_data: yaml string with object data; the data has to be signed correctly
        :return: WildlandResult and WLObject of appropriate type
        """

    @abc.abstractmethod
    def object_get(self, object_type: WLObjectType, object_name: str) -> \
            Tuple[WildlandResult, Optional[WLObject]]:
        """
        Find provided WL object.
        :param object_name: name of the object: can be the file name or user fingerprint or URL
         (but not local path - in case of local path object should be loaded by object_info)
        :param object_type: type of the object
        :return: tuple of WildlandResult and object, if found
        """

    @abc.abstractmethod
    def user_get_usages(self, user_id: str) -> Tuple[WildlandResult, List[WLObject]]:
        """
        Get all usages of the given user in the local context, e.g. objects owned by them.
        :param user_id: user's id
        :return: tuple of WildlandResult and list of objects found
        """

    @abc.abstractmethod
    def object_sign(self, object_data: str) -> Tuple[WildlandResult, Optional[str]]:
        """
        Sign Wildland manifest data.
        :param object_data: object data to sign.
        :return: tuple of WildlandResult and string data (if signing was successful)
        """

    @abc.abstractmethod
    def object_export(self, object_type: WLObjectType, object_id: str, decrypt: bool = True) -> \
            Tuple[WildlandResult, Optional[str]]:
        """
        Get raw object manifest
        :param object_id: object_id of the object
        :param object_type: type of the object
        :param decrypt: should the manifest be decrypted as much as possible
        """

    @abc.abstractmethod
    def object_import_from_yaml(self, yaml_data: bytes, object_name: Optional[str]) -> \
            Tuple[WildlandResult, Optional[WLObject]]:
        """
        Import object from raw data. Only copies the provided object to appropriate WL manifest
        directory, does not create any bridges or other objects.
        :param yaml_data: bytes with yaml manifest data; must be correctly signed
        :param object_name: name of the object to be created; if not provided, will be generated
        automatically
        """

    @abc.abstractmethod
    def object_import_from_url(self, url: str, object_name: Optional[str]) -> \
            Tuple[WildlandResult, Optional[WLObject]]:
        """
        Import object from raw data. Only copies the provided object to appropriate WL manifest
        directory, does not create any bridges or other objects.
        :param url: url to object manifest
        :param object_name: name of the object to be created
        """

    @abc.abstractmethod
    def object_check_published(self, object_type: WLObjectType, object_id: str) -> \
            Tuple[WildlandResult, Optional[bool]]:
        """
        Check if provided object is published.
        :param object_id: object_id of the object
        :param object_type: type of the object
        :return: tuple of WildlandResult and publish status, if available
        :rtype:
        """

    @abc.abstractmethod
    def object_get_local_path(self, object_type: WLObjectType, object_id: str) -> \
            Tuple[WildlandResult, Optional[str]]:
        """
        Return local path to object, if available.
        :param object_id: object_id of the object
        :param object_type: type of the object
        :return: tuple of WildlandResult and local file path or equivalent, if available
        """

    @abc.abstractmethod
    def object_update(self, updated_object: WLObject) -> Tuple[WildlandResult, Optional[str]]:
        """
        Perform a batch of upgrades on an object. Currently just able to replace an existing object
        of a given ID, regardless of its previous state, but in the future it should take note
        of explicit manifest versioning and reject any changes that are performed on an obsolete
        version.
        :param updated_object: Any WLObject
        :return: Wildland Result determining whether change was successful and, if it was, id of
        the modified object
        """

    @abc.abstractmethod
    def put_file(self, local_file_path: str, wl_path: str) -> WildlandResult:
        """
        Put a file under Wildland path
        :param local_file_path: path to local file
        :param wl_path: Wildland path
        :return: WildlandResult
        """

    @abc.abstractmethod
    def put_data(self, data_bytes: bytes, wl_path: str) -> WildlandResult:
        """
        Put a file under Wildland path
        :param data_bytes: bytes to put in the provided location
        :param wl_path: Wildland path
        :return: WildlandResult
        """

    @abc.abstractmethod
    def get_file(self, local_file_path: str, wl_path: str) -> WildlandResult:
        """
        Get a file, given its Wildland path. Saves to a file.
        :param local_file_path: path to local file
        :param wl_path: Wildland path
        :return: WildlandResult
        """

    @abc.abstractmethod
    def get_data(self, wl_path: str) -> Tuple[WildlandResult, Optional[bytes]]:
        """
        Get a file, given its Wildland path. Returns data.
        :param wl_path: Wildland path
        :return: Tuple of WildlandResult and bytes (if successful)
        """

    @abc.abstractmethod
    def start_wl(self, remount: bool = False, single_threaded: bool = False,
                 default_user: Optional[str] = None,
                 callback: Callable[[WLContainer], None] = None) -> WildlandResult:
        """
        Mount the Wildland filesystem into config's mount_dir.
        :param remount: if mounted already, remount
        :param single_threaded: run single-threaded
        :param default_user: specify a default user to be used
        :param callback: a function from WLContainer to None that will be called before each
         mounted container
        :return: WildlandResult
        """

    @abc.abstractmethod
    def stop_wl(self) -> WildlandResult:
        """
        Unmount the Wildland filesystem.
        """

    # USER METHODS
    @abc.abstractmethod
    def user_get_by_id(self, user_id: str) -> Tuple[WildlandResult, Optional[WLUser]]:
        """
        Get user from specified ID.
        """

    @abc.abstractmethod
    def user_generate_key(self) -> Tuple[WildlandResult, Optional[str], Optional[str]]:
        """
        Generate a new encryption and signing key(s), store them in an appropriate location and
        return key owner id and public key generated.
        """

    @abc.abstractmethod
    def user_remove_key(self, owner: str, force: bool) -> WildlandResult:
        """
        Remove an existing encryption/signing key. If force is False, the key will not be removed
        if there are any users who use it as a secondary encryption key.
        """

    @abc.abstractmethod
    def user_import_key(self, public_key: bytes, private_key: bytes) -> WildlandResult:
        """
        Import provided public and private key. The keys must follow key format appropriate for
        used SigContext (see documentation)
        :param public_key: bytes with public key
        :param private_key: bytes with private key
        :return: WildlandResult
        """

    @abc.abstractmethod
    def user_get_public_key(self, owner: str) -> Tuple[WildlandResult, Optional[str]]:
        """
        Return public key for the provided owner.
        :param owner: owner fingerprint
        :return: Tuple of WildlandResult and, if successful, this user's public key
        """

    @abc.abstractmethod
    def user_create(self, name: Optional[str], keys: List[str], paths: List[str],) -> \
            Tuple[WildlandResult, Optional[WLUser]]:
        """
        Create a user and return information about it
        :param name: file name for the newly created file
        :param keys: list of user's public keys, starting with their own key
        :param paths: list of user paths (paths must be absolute paths)
        :return: Tuple of WildlandResult , WLUser (if creation was successful)
        """

    @abc.abstractmethod
    def user_list(self) -> Tuple[WildlandResult, List[WLUser]]:
        """
        List all known users.
        :return: WildlandResult, List of WLUsers
        """

    @abc.abstractmethod
    def user_delete(self, user_id: str) -> WildlandResult:
        """
        Delete provided user.
        :param user_id: User ID (in the form of user fingerprint)
        :return: WildlandResult
        """

    @abc.abstractmethod
    def user_refresh(self, user_ids: Optional[List[str]] = None) -> WildlandResult:
        """
        Iterates over bridges and fetches each user's file from the URL specified in the bridge
        :param user_ids: Optional list of user_ids to refresh; if None, will refresh all users
            with a bridge present
        :return: WildlandResult
        """

    @abc.abstractmethod
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

    @abc.abstractmethod
    def user_publish(self, user_id) -> WildlandResult:
        """
        Publish the given user.
        :param user_id: fingerprint of the user to be published
        :return: WildlandResult
        """

    @abc.abstractmethod
    def user_unpublish(self, user_id) -> WildlandResult:
        """
        Unpublish the given user.
        :param user_id: fingerprint of the user to be unpublished
        :return: WildlandResult
        """

    # BRIDGES
    @abc.abstractmethod
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

    @abc.abstractmethod
    def bridge_list(self) -> Tuple[WildlandResult, List[WLBridge]]:
        """
        List all known bridges.
        :return: WildlandResult, List of WLBridges
        """

    @abc.abstractmethod
    def bridge_delete(self, bridge_id: str) -> WildlandResult:
        """
        Delete provided bridge.
        :param bridge_id: Bridge ID (in the form of user_id:/.uuid/bridge_uuid)
        :return: WildlandResult
        """

    @abc.abstractmethod
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

    @abc.abstractmethod
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

    @abc.abstractmethod
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

    @abc.abstractmethod
    def bridge_publish(self, bridge_id) -> WildlandResult:
        """
        Publish the given bridge.
        :param bridge_id: id of the bridge to be published (user_id:/.uuid/bridge_uuid)
        :return: WildlandResult
        """

    @abc.abstractmethod
    def bridge_unpublish(self, bridge_id) -> WildlandResult:
        """
        Unpublish the given bridge.
        :param bridge_id: id of the bridge to be unpublished (user_id:/.uuid/bridge_uuid)
        :return: WildlandResult
        """

    # CONTAINERS
    @abc.abstractmethod
    def container_create(self, paths: List[str],
                         access_users: Optional[List[str]] = None,
                         encrypt_manifest: bool = True,
                         categories: Optional[List[str]] = None,
                         title: Optional[str] = None, owner: Optional[str] = None,
                         name: Optional[str] = None) -> \
            Tuple[WildlandResult, Optional[WLContainer]]:
        """
        Create a new container manifest
        :param paths: container paths (must be absolute paths)
        :param access_users: list of additional users who should be able to access this manifest;
        provided as either user fingerprints or WL paths to users.
        Mutually exclusive with encrypt_manifest=False
        :param encrypt_manifest: whether container manifest should be encrypted. Default: True.
        Mutually exclusive with a not-None access_users
        :param categories: list of categories, will be used to generate mount paths
        :param title: title of the container, will be used to generate mount paths
        :param owner: owner of the container; if omitted, default owner will be used
        :param name: name of the container to be created, used in naming container file
        :return: Tuple of WildlandResult and, if successful, the created WLContainer
        """

    @abc.abstractmethod
    def container_list(self) -> Tuple[WildlandResult, List[WLContainer]]:
        """
        List all known containers.
        :return: WildlandResult, List of WLContainers
        """

    @abc.abstractmethod
    def container_delete(self, container_id: str) -> WildlandResult:
        """
        Delete provided container.
        :param container_id: container ID (in the form of user_id:/.uuid/container_uuid)
        """

    @abc.abstractmethod
    def container_duplicate(self, container_id: str, name: Optional[str] = None) -> \
            Tuple[WildlandResult, Optional[WLContainer]]:
        """
        Create a copy of the provided container at the provided friendly name, with a newly
        generated id and copied storages
        :param container_id: id of the container to be duplicated, in the form of
        owner_id:/.uuid/container_uuid
        :param name: optional name for the new container. If omitted, will be generated
        automatically
        :return: WildlandResult and, if duplication was successful, the new container
        """

    @abc.abstractmethod
    def container_import_from_data(self, yaml_data: str, overwrite: bool = True) -> \
            Tuple[WildlandResult, Optional[WLContainer]]:
        """
        Import container from provided yaml data.
        :param yaml_data: yaml data to be imported
        :param overwrite: if a container of provided uuid already exists, overwrite it;
        default: True. If this is False and the container already exists, this operation will fail.
        :return: tuple of WildlandResult, imported WLContainer (if import was successful)
        """

    @abc.abstractmethod
    def container_create_cache(self, container_id: str, storage_template_name: str) \
            -> WildlandResult:
        """
        Create cache storage for a container.
        :param container_id: id of the container (in the form of its publish_path,
        userid:/.uuid/container_uuid)
        :param storage_template_name: use the specified storage template to create a new
        cache storage (becomes primary storage for the container while mounted)
        :return: WildlandResult
        :rtype:
        """

    @abc.abstractmethod
    def container_delete_cache(self, container_id: str) -> WildlandResult:
        """
        Delete cache storage for container.
        :param container_id: id of the container (in the form of its publish_path,
        userid:/.uuid/container_uuid)
        :return: WildlandResult
        """

    # @abc.abstractmethod
    # def container_mount_watch(self, container_ids: List[str]) -> WildlandResult:
    #     """
    #     Watch for manifest files inside Wildland, and keep the filesystem mount
    #     state in sync. This function ends only when the process is killed or when an unrecoverable
    #     error occurs.
    #     # TODO: this requires significant rewrite or perhaps should be hidden from API completely.
    #     :param container_ids:
    #     :return: WildlandResult
    #     """

    @abc.abstractmethod
    def container_modify(self, container_id: str, manifest_field: str, operation: ModifyMethod,
                         modify_data: List[str]) -> WildlandResult:
        """
        Modify container manifest
        :param container_id: id of the container to be modified, in the form of
        user_id:/.uuid/container_uuid
        :param manifest_field: field to modify; supports the following:
            - paths
            - categories
            - title
            - access
        :param operation: operation to perform on field ('add', 'delete' or 'set')
        :param modify_data: list of values to be added/removed
        :return: WildlandResult
        """

    @abc.abstractmethod
    def container_publish(self, container_id) -> WildlandResult:
        """
        Publish the given container.
        :param container_id: id of the container to be published (user_id:/.uuid/container_uuid)
        :return: WildlandResult
        """

    @abc.abstractmethod
    def container_unpublish(self, container_id) -> WildlandResult:
        """
        Unpublish the given container.
        :param container_id: id of the container to be unpublished (user_id:/.uuid/container_uuid)
        :return: WildlandResult
        """

    @abc.abstractmethod
    def container_find(self, path: str) -> \
            Tuple[WildlandResult, List[Tuple[WLContainer, WLStorage]]]:
        """
        Find container by path relative to Wildland mount root.
        :param path: path to file (relative to Wildland mount root)
        :return: tuple of WildlandResult and list of tuples of WLContainer, WLStorage that contain
        the provided path
        """

    # STORAGES

    @abc.abstractmethod
    def supported_storage_backends(self) -> Tuple[WildlandResult, List[WLStorageBackend]]:
        """
        List all supported storage backends.
        :return: WildlandResult and a list of supported storage backends.
        """

    @abc.abstractmethod
    def storage_create(self, backend_type: str, backend_params: Dict[str, str],
                       container_id: str, trusted: bool = False,
                       watcher_interval: Optional[int] = 0,
                       access_users: Optional[list[str]] = None, encrypt_manifest: bool = True) -> \
            Tuple[WildlandResult, Optional[WLStorage]]:
        """
        Create a storage.
        :param backend_type: storage type
        :param backend_params: params for the given backend as a dict of param_name, param_value.
        They must conform to parameter names as provided by supported_storage_backends
        :param container_id: container this storage is for
        :param trusted: should the storage be trusted
        :param watcher_interval: set the storage watcher-interval in seconds
        :param access_users: limit access to this storage to the users provided here as either
        user fingerprints or WL paths to users.
        Default: same as the container
        :param encrypt_manifest: should the storage manifest be encrypted. If this is False,
        access_users should be None. The container manifest itself might also be encrypted or not,
        this does not change its settings.
        :return: Tuple of WildlandResult and, if creation was successful, WLStorage that was
        created
        """

    @abc.abstractmethod
    def storage_create_from_template(self, template_name: str, container_id: str,
                                     local_dir: Optional[str] = None):
        """
        Create storages for a container from a given storage template.
        :param template_name: name of the template
        :param container_id: container this storage is for
        :param local_dir: str to be passed to template renderer as a parameter, can be used by
        template creators
        """

    @abc.abstractmethod
    def storage_list(self) -> Tuple[WildlandResult, List[WLStorage]]:
        """
        List all known storages.
        :return: WildlandResult, List of WLStorages
        """

    @abc.abstractmethod
    def storage_delete(self, storage_id: str, cascade: bool = True,
                       force: bool = False) -> WildlandResult:
        """
        Delete provided storage.
        :param storage_id: storage ID
         (in the form of user_id:/.uuid/container_uuid:/.uuid/storage_uuid)
        :param cascade: remove reference from containers
        :param force: delete even if used by containers or if manifest cannot be loaded
        :return: WildlandResult
        """

    @abc.abstractmethod
    def storage_import_from_data(self, yaml_data: str, overwrite: bool = True) -> \
            Tuple[WildlandResult, Optional[WLStorage]]:
        """
        Import storage from provided yaml data.
        :param yaml_data: yaml data to be imported
        :param overwrite: if a storage of provided uuid already exists in the appropriate container,
        overwrite it; default: True. If this is False and the storage already exists, this
         operation will fail.
        :return: tuple of WildlandResult, imported WLStorage (if import was successful)
        """

    @abc.abstractmethod
    def storage_modify(self, storage_id: str, manifest_field: str, operation: ModifyMethod,
                       modify_data: List[str]) -> WildlandResult:
        """
        Modify storage manifest
        :param storage_id: id of the storage to be modified, in the form of
        user_id:/.uuid/container_uuid:/.uuid/storage_uuid
        :param manifest_field: field to modify; supports the following:
            - location
            - access
        :param operation: operation to perform on field ('add', 'delete' or 'set')
        :param modify_data: list of values to be added/removed
        :return: WildlandResult
        """

    @abc.abstractmethod
    def storage_publish(self, storage_id) -> WildlandResult:
        """
        Publish the given storage.
        :param storage_id: id of the storage to be published
         (user_id:/.uuid/container_uuid:/.uuid/storage_uuid)
        :return: WildlandResult
        """

    @abc.abstractmethod
    def storage_unpublish(self, storage_id) -> WildlandResult:
        """
        Unpublish the given storage.
        :param storage_id: id of the storage to be unpublished
         (user_id:/.uuid/container_uuid:/.uuid/storage_uuid)
        :return: WildlandResult
        """

    # TEMPLATES
    @abc.abstractmethod
    def template_create(self, name: str) -> Tuple[WildlandResult, Optional[WLTemplateFile]]:
        """
        Create a new empty template file under the provided name.
        :param name: name of the template to be created
        :return: Tuple of WildlandResult and, if creation was successful, WLTemplateFile that was
        created
        """

    @abc.abstractmethod
    def template_add_storage(self, backend_type: str, backend_params: Dict[str, str],
                             template_name: str, read_only: bool = False,
                             default_cache: bool = False, watcher_interval: Optional[int] = 0,
                             access_users: Optional[list[str]] = None,
                             encrypt_manifest: bool = True) -> \
            Tuple[WildlandResult, Optional[WLTemplateFile]]:
        """
        Add a storage template to a template file.
        :param backend_type: storage type
        :param backend_params: params for the given backend as a dict of param_name, param_value.
        They must conform to parameter names as provided by supported_storage_backends
        :param template_name: name of an existing template file to use
        :param read_only: should the storage be read-only
        :param default_cache: mark template as default for container caches
        :param watcher_interval: set the storage watcher-interval in seconds
        :param access_users: limit access to this storage to the users provided here as a list of
        either user fingerprints or WL paths.
        Default: same as the container
        :param encrypt_manifest: should the storage manifest be encrypted. If this is False,
        access_users should be None. The container manifest itself might be encrypted, this does
        not change its settings.
        :return: Tuple of WildlandResult and, if adding was successful, WLTemplate that was
        modified
        """

    @abc.abstractmethod
    def template_list(self) -> Tuple[WildlandResult, List[WLTemplateFile]]:
        """
        List all known templates.
        :return: WildlandResult, List of WLTemplateFiles
        """

    @abc.abstractmethod
    def template_delete(self, template_name: str) -> WildlandResult:
        """
        Delete a template
        :param template_name: name of template to be deleted.
        """

    @abc.abstractmethod
    def template_export(self, template_name: str) -> Tuple[WildlandResult, Optional[str]]:
        """
        Return (if possible) contents of the provided template
        :param template_name: name of the template
        """

    @abc.abstractmethod
    def template_import(self, template_name: str, template_data: str) -> WildlandResult:
        """
        Import template from provided data.
        :param template_name: Name to be used for the template. If it exists, the contents
        will be replaced
        :param template_data: jinja template data
        """

    # FORESTS

    @abc.abstractmethod
    def forest_create(self, storage_template: str, user_id: str,
                      access_users: Optional[List[str]] = None, encrypt: bool = True,
                      manifests_local_dir: Optional[str] = '/.manifests') -> WildlandResult:
        """
        Bootstrap a new forest
        :param storage_template: name of the template to be used for forest creation; must contain
        at least one writeable storage
        :param user_id: fingerprint of the user for whom the forest will be created
        :param access_users: list of additional users to the container to; provided as a list of
        either user fingerprints or WL paths to users
        :param encrypt: if the container should be encrypted; mutually exclusive with
        access_users
        :param manifests_local_dir: manifests local directory. Must be an absolute path
        :return: WildlandResult
        """

    # MOUNTING

    @abc.abstractmethod
    def mount(self, paths_or_names: List[str], include_children: bool = True,
              include_parents: bool = True, remount: bool = True,
              import_users: bool = True, manifests_catalog: bool = False,
              callback: Callable[[WLContainer], None] = None) ->\
            Tuple[WildlandResult, List[WLContainer]]:
        """
        Mount containers given by name or path to their manifests or WL path to containers to
        be mounted.
        :param paths_or_names: list of container names, urls or WL urls to be mounted
        :param include_children: mount subcontainers/children of the containers found
        :param include_parents: mount main containers/parent containers even if
        subcontainers/children are found
        :param remount: remount already mounted containers, if found
        :param import_users: import users encountered on the WL path
        :param manifests_catalog: allow manifest catalogs themselves
        :param callback: a function that takes WLContainer and will be called before each container
        mount
        :return: Tuple of WildlandResult, List of successfully mounted containers; WildlandResult
        contains the list of containers that were not mounted for various reasons (from errors to
        being already mounted)
        """

    @abc.abstractmethod
    def unmount_all(self) -> WildlandResult:
        """
        Unmount all mounted containers.
        """

    @abc.abstractmethod
    def unmount_by_mount_path(self, paths: List[str], include_children: bool = True) -> \
            WildlandResult:
        """
        Unmount mounted containers by mount paths
        :param paths: list of mount paths to unmount
        :param include_children: should subcontainers/children be unmounted (default: true)
        :return: WildlandResult
        """

    @abc.abstractmethod
    def unmount_by_path_or_name(self, path_or_name: List[str], include_children: bool = True) -> \
            WildlandResult:
        """
        Unmount containers given by name or path to their manifests or WL path to containers to
        be mounted.
        :param path_or_name:
        :type path_or_name:
        :param include_children: should subcontainers/children be unmounted (default: true)
        :return: WildlandResult
        """

    @abc.abstractmethod
    def mount_status(self) -> Tuple[WildlandResult, List[WLContainer]]:
        """
        List all mounted containers
        :return: tuple of WildlandResult and mounted WLContainers
        """
