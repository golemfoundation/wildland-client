from .wildland_core_api import WildlandResult, WildlandCoreApi, WLUser, WLBridge, \
    WLStorageBackend, WLStorage, WLContainer, WLError, WLObject, WLTemplateFile, ModifyMethod
from ..client import Client
from ..user import User
from ..container import Container
from ..bridge import Bridge
from ..storage import Storage
from ..wildland_object.wildland_object import WildlandObject
from ..manifest.manifest import ManifestError
from ..manifest.sig import SigError
from ..manifest.schema import SchemaError
from copy import deepcopy

from typing import List, Tuple, Optional, Callable, Any, TypeVar
from pathlib import PurePosixPath
import binascii

# For the purposes of communicating with wildland core, we shall use unique object ids,
# with syntax same as with current WL paths:
# 0xaaa:[/.uuid/000-000-000:/.uuid/000-000-000]
# USERS: userid:
# BRIDGES: ownerid:uuid
# CONTAINERS: ownerid:uuid
# STORAGES: ownerid:container_uuid:uuid

# All helper objects should be dataclasses with fields with only simple types or lists of such types

# Style goal: All methods must be <15 functional lines of code; if more, refactor

# TODO: core should have its own tests, possibly test_cli should be remade to test WildlandCore, and
# TODO cli should get its own, simple tests with mocked


def wrap_exception(exc: Exception, is_recoverable: bool = False) -> WLError:
    error_desc = str(exc)
    if isinstance(exc, ManifestError):
        # TODO: more elaborate error reporting
        err_code = 1
    elif isinstance(exc, SigError):
        err_code = 2
    elif isinstance(exc, SchemaError):
        err_code = 3
    elif isinstance(exc, binascii.Error):
        err_code = 101
        error_desc = "Incorrect public key provided; provide key, not filename or path."
    else:
        err_code = 999
    error = WLError(error_code=err_code,
                    error_description=error_desc, is_recoverable=is_recoverable)
    return error
# error code 100: incorrect input value


class WildlandCore(WildlandCoreApi):
    # All user-facing methods should be wrapped in wildland_result_wrapper or otherwise assure
    # they wrap all exceptions in WildlandResult
    def __init__(self, client: Client):
        # TODO: once cli is decoupled from client, this should take more raw params
        self.client = client

    # client = Client(dummy=dummy, base_dir=base_dir)
    # ctx.obj = ContextObj(client)

    # private methods
    def _user_to_wluser(self, user: User) -> WLUser:
        # TODO: optimize for possible lazy loading of catalog manifests
        wl_user = WLUser(
            owner=user.owner,
            id=f'{user.owner}:',
            private_key_available=self.client.session.sig.is_private_key_available(user.owner),
            published=False,  # TODO
            pubkeys=deepcopy(user.pubkeys),
            paths=[str(p) for p in user.paths],
            local_path=str(user.local_path) if user.local_path else None,
            manifest_catalog_description=[c for c in user.get_catalog_descriptions()],
            # manifest_catalog_ids=[container.uuid_path for container in user.load_catalog(False)],
        )
        # TODO: currently loading user's catalog messes up their catalog descriptions, which is not
        # ideal, but it's an old bug, not introduced by WLCore
        return wl_user

    @staticmethod
    def _container_to_wlcontainer(container: Container) -> WLContainer:
        wl_container = WLContainer(
            owner=container.owner,
            id=str(container.uuid_path),
            published=False,  # TODO
            paths=[str(p) for p in container.paths],
            title=container.title,
            categories=[str(c) for c in container.categories],
            access_ids=[],  # TODO
            storage_ids=[],  # TODO
            storage_description=[],  # TODO
            local_path=str(container.local_path) if container.local_path else None
        )
        return wl_container

    @staticmethod
    def _bridge_to_wl_bridge(bridge: Bridge) -> WLBridge:
        wl_bridge = WLBridge(
            owner=bridge.owner,
            id=str(bridge.paths[0]),  # TODO
            user_pubkey=bridge.user_pubkey,
            user_id=bridge.user_id,
            published=False,  # TODO
            user_location_description="",  # TODO
            paths=[str(p) for p in bridge.paths],
            local_path=str(bridge.local_path) if bridge.local_path else None
        )
        return wl_bridge

    @staticmethod
    def _storage_to_wl_storage(storage: Storage) -> WLStorage:
        wl_storage = WLStorage(
            owner=storage.owner,
            id=str(storage.get_unique_publish_id()),  # TODO
            storage_type=storage.storage_type,
            published=False,  # TODO
            container="",  # TODO
            trusted=storage.trusted,
            primary=storage.primary,
            access_ids=[],  # TODO
            local_path=str(storage.local_path) if storage.local_path else None
        )
        return wl_storage

    # TODO: remove WLStorageBackend

    # GENERAL METHODS
    def object_info(self, yaml_data: str) -> Tuple[WildlandResult, Optional[WLObject]]:
        """
        This method parses yaml data and returns an appropriate WLObject; to perform any further
        operations the object has to be imported.
        :param yaml_data: yaml string with object data; has to be appropriately signed
        :return: WildlandResult and WLObject of appropriate type
        """
        wildland_result = WildlandResult()
        try:
            obj = self.client.load_object_from_bytes(None, yaml_data.encode())
        except Exception as ex:
            wildland_result.errors.append(wrap_exception(ex, False))
            return wildland_result, None
        if isinstance(obj, User):
            return wildland_result, self._user_to_wluser(obj)
        elif isinstance(obj, Container):
            return wildland_result, self._container_to_wlcontainer(obj)
        elif isinstance(obj, Bridge):
            return wildland_result, self._bridge_to_wl_bridge(obj)
        elif isinstance(obj, Storage):
            return wildland_result, self._storage_to_wl_storage(obj)
        # TODO: Add error code: unknown object
        error = WLError(error_code=700, error_description="Unknown object type encountered",
                        is_recoverable=False, diagnostic_info=yaml_data)
        wildland_result.errors.append(error)
        return wildland_result, None

    def object_sign(self, object_data: str) -> Tuple[WildlandResult, Optional[str]]:
        """
        Sign Wildland manifest data.
        :param object_data: object data to sign.
        :return: tuple of WildlandResult and string data (if signing was successful)
        """
        # TODO

    def object_verify(self, object_data: str, verify_signature: bool = True) -> WildlandResult:
        """
        Verify if the data provided is a correct Wildland object manifest.
        :param object_data: object data to verify
        :param verify_signature: should we also check if the signature is correct; default: True
        :rtype: WildlandResult
        """
        # TODO

    def put_file(self, local_file_path: str, wl_path: str) -> WildlandResult:
        """
        Put a file under Wildland path
        :param local_file_path: path to local file
        :param wl_path: Wildland path
        :return: WildlandResult
        """
        # TODO

    def put_data(self, data_bytes: bytes, wl_path: str) -> WildlandResult:
        """
        Put a file under Wildland path
        :param data_bytes: bytes to put in the provided location
        :param wl_path: Wildland path
        :return: WildlandResult
        """
        # TODO

    def get_file(self, local_file_path: str, wl_path: str) -> WildlandResult:
        """
        Get a file, given its Wildland path. Saves to a file.
        :param local_file_path: path to local file
        :param wl_path: Wildland path
        :return: WildlandResult
        """
        # TODO

    def get_data(self, wl_path: str) -> Tuple[WildlandResult, Optional[bytes]]:
        """
        Get a file, given its Wildland path. Returns data.
        :param wl_path: Wildland path
        :return: Tuple of WildlandResult and bytes (if successful)
        """
        # TODO

    def start_wl(self, remount: bool = False, single_threaded: bool = False,
                 skip_default: bool = False, skip_forest: bool = False,
                 default_user: Optional[str] = None,
                 callback: Callable[[WLContainer], None] = None) -> WildlandResult:
        """
        Mount the Wildland filesystem into config's mount_dir.
        :param remount: if mounted already, remount
        :param single_threaded: run single-threaded
        :param skip_default: skip mounting default-containers from config
        :param skip_forest: skip mounting forest of default user
        :param default_user: specify a default user to be used
        :param callback: a function from WLContainer to None that will be called before each
         mounted container
        :return: WildlandResult
        """
        # TODO

    def stop_wl(self) -> WildlandResult:
        """
        Unmount the Wildland filesystem.
        """
        # TODO

    # USER METHODS
    # TODO: when @prbartman's changes are finished, wrap everything into wlresult wrap
    def user_generate_key(self) -> Tuple[WildlandResult, Optional[str], Optional[str]]:
        """
        Generate a new encryption key, store it in an appropriate location and return key owner id
        and public key generated.
        """
        result = WildlandResult()
        try:
            owner, pubkey = self.client.session.sig.generate()
        except Exception as ex:
            result.errors.append(wrap_exception(ex))
            owner, pubkey = None, None
        return result, owner, pubkey

    def user_remove_key(self, owner: str) -> WildlandResult:
        """
        Remove an existing encryption key.
        """
        wl_result = WildlandResult()
        try:
            self.client.session.sig.remove_key(owner)
        except Exception as ex:
            wl_result.errors.append(wrap_exception(ex))
        return wl_result

    def user_create(self, name: str, keys: List[str], paths: List[str],) -> \
            Tuple[WildlandResult, Optional[WLUser]]:
        """
        Create a user and return information about it
        :param name: file name for the newly created file
        :param keys: list of user's public keys, starting with their own key
        :param paths: list of user paths (paths must be absolute paths)
        """
        result = WildlandResult()

        if not keys:
            result.errors.append(WLError(100, "At least one public key must be provided", False))
            return result, None

        owner = self.client.session.sig.fingerprint(keys[0])
        user = User(
            owner=owner,
            pubkeys=keys,
            paths=[PurePosixPath(p) for p in paths],
            manifests_catalog=[],
            client=self.client)

        try:
            self.client.save_new_object(WildlandObject.Type.USER, user, name)
        except Exception as ex:
            result.errors.append(wrap_exception(ex))

        user.add_user_keys(self.client.session.sig)
        wl_user = self._user_to_wluser(user)
        return result, wl_user

    def user_list(self) -> Tuple[WildlandResult, List[WLUser]]:
        """
        List all known users.
        :return: WildlandResult, List of WLUsers
        """
        wildland_result = WildlandResult()
        result_list = []
        try:
            for user in self.client.load_all(WildlandObject.Type.USER):
                result_list.append(self._user_to_wluser(user))
        except Exception as ex:
            wildland_result.errors.append(wrap_exception(ex))
        return wildland_result, result_list

    def user_delete(self, user_id: str, cascade: bool = False,
                    force: bool = False, delete_keys: bool = False) -> WildlandResult:
        """
        Delete provided user.
        :param user_id: User ID (in the form of user fingerprint)
        :param cascade: remove all of user's containers and storage as well
        :param force: delete even if still has containers/storage
        :param delete_keys: also remove user keys
        :return: WildlandResult
        """
        # TODO

    def user_export(self, user_id: str) -> Tuple[WildlandResult, Optional[str]]:
        """
        Get raw user information (the manifest contents, decrypted as much as possible)
        :param user_id: user_id (fingerprint) of the user
        """
        # TODO

    def user_import_from_path(self, path_or_url: str, paths: List[str], object_owner: Optional[str],
                              only_first: bool = False) -> Tuple[WildlandResult, Optional[WLUser]]:
        """
        Import user from provided url or path.
        :param path_or_url: WL path, local path or URL
        :param paths: list of paths for resulting bridge manifest; if omitted, will use imported
            user's own paths
        :param object_owner: specify a different-from-default user to be used as the owner of
            created bridge manifests
        :param only_first: import only first encountered bridge (ignored in all cases except
            WL container paths)
        :return: tuple of WildlandResult, imported WLUser (if import was successful
        """
        # TODO

    def user_import_from_data(self, yaml_data: str, paths: List[str],
                              object_owner: Optional[str]) -> \
            Tuple[WildlandResult, Optional[WLUser]]:
        """
        Import user from provided yaml data.
        :param yaml_data: yaml data to be imported
        :param paths: list of paths for resulting bridge manifest; if omitted, will use imported
            user's own paths
        :param object_owner: specify a different-from-default user to be used as the owner of
            created bridge manifests
        :return: tuple of WildlandResult, imported WLUser (if import was successful
        """
        # TODO

    def user_refresh(self, user_ids: Optional[List[str]] = None,
                     callback: Callable[[str], None] = None) -> WildlandResult:
        """
        Iterates over bridges and fetches each user's file from the URL specified in the bridge
        :param user_ids: Optional list of user_ids to refresh; if None, will refresh all users
            with a bridge present
        :param callback: function to be called before each refreshed user
        :return: WildlandResult
        """
        # TODO

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
        # TODO

    def user_publish(self, user_id) -> WildlandResult:
        """
        Publish the given user.
        :param user_id: fingerprint of the user to be published
        :return: WildlandResult
        """
        # TODO

    def user_unpublish(self, user_id) -> WildlandResult:
        """
        Unpublish the given user.
        :param user_id: fingerprint of the user to be unpublished
        :return: WildlandResult
        """
        # TODO

    # BRIDGES
    def bridge_create(self, paths: Optional[List[str]], owner: Optional[str] = None,
                      target_user: Optional[str] = None, target_user_url: Optional[str] = None,
                      file_path: Optional[str] = None) -> Tuple[WildlandResult, Optional[WLBridge]]:
        """
        Create a new bridge
        :param paths: paths for user in owner namespace (of None, will be taken from user manifest)
        :param owner: user_id for the owner of the created bridge
        :param target_user: user_id to whom the bridge will point. If provided, will be used to
        verify the integrity of the target_user_url
        :param target_user_url: path to the user manifest (use file:// for local file).
        If target_user is skipped, the user manifest from this path is considered trusted.
        If omitted,the user manifest will be located in their manifests catalog.
        :param file_path: file path to create the bridge under
        :return: tuple of WildlandResult and, if successful, the created WLBridge
        """
        # TODO

    def bridge_list(self) -> Tuple[WildlandResult, List[WLBridge]]:
        """
        List all known bridges.
        :return: WildlandResult, List of WLBridges
        """
        wildland_result = WildlandResult()
        result_list = []
        try:
            for bridge in self.client.load_all(WildlandObject.Type.BRIDGE):
                result_list.append(self._bridge_to_wl_bridge(bridge))
        except Exception as ex:
            wildland_result.errors.append(wrap_exception(ex))
        return wildland_result, result_list

    def bridge_delete(self, bridge_id: str) -> WildlandResult:
        """
        Delete provided bridge.
        :param bridge_id: Bridge ID (in the form of user_id:/.uuid/bridge_uuid)
        :return: WildlandResult
        """
        # TODO

    def bridge_export(self, bridge_id: str) -> Tuple[WildlandResult, Optional[str]]:
        """
        Get raw bridge information (the manifest contents, decrypted as much as possible)
        :param bridge_id: bridge_id of the bridge (provided as user_id:/.uuid/bridge_uuid
        """
        # TODO

    def bridge_import(self, path_or_url: str, paths: List[str], object_owner: Optional[str],
                      only_first: bool = False) -> Tuple[WildlandResult, Optional[WLBridge]]:
        """
        Import bridge from provided url or path.
        :param path_or_url: WL path, local path or URL
        :param paths: list of paths for resulting bridge manifest; if omitted, will use imported
            user's own paths
        :param object_owner: specify a different-from-default user to be used as the owner of
            created bridge manifests
        :param only_first: import only first encountered bridge (ignored in all cases except
            WL container paths)
        :return: tuple of WildlandResult, imported WLBridge (if import was successful
        """
        # TODO

    def bridge_import_from_data(self, yaml_data: str, paths: List[str],
                                object_owner: Optional[str]) -> \
            Tuple[WildlandResult, Optional[WLBridge]]:
        """
        Import bridge from provided yaml data.
        :param yaml_data: yaml data to be imported
        :param paths: list of paths for resulting bridge manifest; if omitted, will use imported
            user's own paths
        :param object_owner: specify a different-from-default user to be used as the owner of
            created bridge manifests
        :return: tuple of WildlandResult, imported WLUser (if import was successful
        """
        # TODO

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
        # TODO

    def bridge_publish(self, bridge_id) -> WildlandResult:
        """
        Publish the given bridge.
        :param bridge_id: id of the bridge to be published (user_id:/.uuid/bridge_uuid)
        :return: WildlandResult
        """
        # TODO

    def bridge_unpublish(self, bridge_id) -> WildlandResult:
        """
        Unpublish the given bridge.
        :param bridge_id: id of the bridge to be unpublished (user_id:/.uuid/bridge_uuid)
        :return: WildlandResult
        """
        # TODO

    # CONTAINERS
    def container_create(self, paths: List[str],
                         access_user_ids: Optional[List[str]] = None,
                         encrypt_manifest: bool = True,
                         categories: Optional[List[str]] = None,
                         title: Optional[str] = None, owner: Optional[str] = None,
                         name: Optional[str] = None) -> \
            Tuple[WildlandResult, Optional[WLContainer]]:
        """
        Create a new container manifest
        :param paths: container paths (must be absolute paths)
        :param access_user_ids: list of additional users who should be able to access this manifest.
        Mutually exclusive with encrypt=False
        :param encrypt_manifest: whether container manifest should be encrypted. Default: True.
        Mutually exclusive with a non-None access_user_ids
        :param categories: list of categories, will be used to generate mount paths
        :param title: title of the container, will be used to generate mount paths
        :param owner: owner of the container; if omitted, default owner will be used
        :param name: name of the container to be created, used in naming container file
        :return: Tuple of WildlandResult and, if successful, the created WLContainer
        """
        # TODO

    def container_list(self) -> Tuple[WildlandResult, List[WLContainer]]:
        """
        List all known containers.
        :return: WildlandResult, List of WLContainers
        """
        # TODO

    def container_delete(self, container_id: str, cascade: bool = False,
                         force: bool = False) -> WildlandResult:
        """
        Delete provided container.
        :param container_id: container ID (in the form of user_id:/.uuid/container_uuid)
        :param cascade: also delete local storage manifests
        :param force: delete even when using local storage manifests; ignore errors on parse
        :return: WildlandResult
        """
        # TODO

    def container_export(self, container_id: str) -> Tuple[WildlandResult, Optional[str]]:
        """
        Get raw container information (the manifest contents, decrypted as much as possible)
        :param container_id: container_id of the container
        (provided as user_id:/.uuid/container_uuid)
        """
        # TODO

    def container_duplicate(self, container_id: str, file_path: Optional[str] = None) -> \
            Tuple[WildlandResult, Optional[WLContainer]]:
        """
        Create a copy of the provided container at the provided file path
        :param container_id: id of the container to be duplicated, in the form of
        owner_id:/.uuid/contaner_uuid
        :param file_path: optional path to new container file. If omitted, will be generated
        automatically
        :return: WildlandResult and, if duplication was successful, the new container
        """
        # TODO

    def container_import_from_data(self, yaml_data: str, overwrite: bool = True) -> \
            Tuple[WildlandResult, Optional[WLContainer]]:
        """
        Import container from provided yaml data.
        :param yaml_data: yaml data to be imported
        :param overwrite: if a container of provided uuid already exists, overwrite it;
        default: True. If this is False and the container already exists, this operation will fail.
        :return: tuple of WildlandResult, imported WLContainer (if import was successful)
        """
        # TODO

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
        # TODO

    def container_delete_cache(self, container_id: str) -> WildlandResult:
        """
        Delete cache storage for container.
        :param container_id: id of the container (in the form of its publish_path,
        userid:/.uuid/container_uuid)
        :return: WildlandResult
        """
        # TODO

    def container_mount_watch(self, container_ids: List[str]) -> WildlandResult:
        """
        Watch for manifest files inside Wildland, and keep the filesystem mount
        state in sync. This function ends only when the process is killed or when an unrecoverable
        error occurs.
        # TODO: this requires FUSE.
        :param container_ids:
        :return: WildlandResult
        """
        # TODO

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
        # TODO

    def container_publish(self, container_id) -> WildlandResult:
        """
        Publish the given container.
        :param container_id: id of the container to be published (user_id:/.uuid/container_uuid)
        :return: WildlandResult
        """
        # TODO

    def container_unpublish(self, container_id) -> WildlandResult:
        """
        Unpublish the given container.
        :param container_id: id of the container to be unpublished (user_id:/.uuid/container_uuid)
        :return: WildlandResult
        """
        # TODO

    def container_find(self, path: str) -> \
            Tuple[WildlandResult, List[Tuple[WLContainer, WLStorage]]]:
        """
        Find container by absolute file path.
        :param path: path to file
        :return: tuple of WildlandResult and list of tuples of WLContainer, WLStorage that contain
        the provided path
        """
        # TODO

    # STORAGES

    def supported_storage_backends(self) -> Tuple[WildlandResult, List[WLStorageBackend]]:
        """
        List all supported storage backends.
        :return: WildlandResult and a list of supported storage backends.
        """
        # TODO

    def storage_create(self, backend_type: str, backend_params: List[str],
                       container_id: str, trusted: bool = False, inline: bool = True,
                       watcher_interval: Optional[int] = 0,
                       access_user_ids: Optional[list[str]] = None, encrypt: bool = True) -> \
            Tuple[WildlandResult, Optional[WLStorage]]:
        """
        Create a storage.
        :param backend_type: storage type
        :param backend_params: params for the given backend, in the order listed by
        supported_storage_backends
        :param container_id: container this storage is for
        :param trusted: should the storage be trusted
        :param inline: inline storages are directly within container manifest, and do not exist as
        separate files
        :param watcher_interval: set the storage watcher-interval in seconds
        :param access_user_ids: limit access to this storage to the provided users.
        Default: same as the container
        :param encrypt: should the storage manifest be encrypted. If this is False, access_user_ids
        should be None. In case of inline storages, container manifest itself might still be
        encrypted, this does not change its settings.
        :return: Tuple of WildlandResult and, if creation was successful, WLStorage that was
        created
        """
        # TODO

    def storage_create_from_template(self, template_name: str, container_id: str,
                                     local_dir: Optional[str] = None):
        """
        Create storages for a container from a given storage template.
        :param template_name: name of the template
        :param container_id: container this storage is for
        :param local_dir: str to be passed to template renderer as a parameter, can be used by
        template creators
        """
        # TODO

    def storage_list(self) -> Tuple[WildlandResult, List[WLStorage]]:
        """
        List all known storages.
        :return: WildlandResult, List of WLStorages
        """
        # TODO

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
        # TODO

    def storage_export(self, storage_id: str) -> Tuple[WildlandResult, Optional[str]]:
        """
        Get raw storage information (the manifest contents, decrypted as much as possible)
        :param storage_id: storage_id of the storage (provided as
        user_id:/.uuid/container_uuid/.uuid/storage_uuid)
        """
        # TODO

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
        # TODO

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
        # TODO

    def storage_publish(self, storage_id) -> WildlandResult:
        """
        Publish the given storage.
        :param storage_id: id of the storage to be published
         (user_id:/.uuid/container_uuid:/.uuid/storage_uuid)
        :return: WildlandResult
        """
        # TODO

    def storage_unpublish(self, storage_id) -> WildlandResult:
        """
        Unpublish the given storage.
        :param storage_id: id of the storage to be unpublished
         (user_id:/.uuid/container_uuid:/.uuid/storage_uuid)
        :return: WildlandResult
        """
        # TODO

    # TEMPLATES

    def template_create(self, backend_type: str, backend_params: List[str], template_name: str,
                        read_only: bool = False, default_cache: bool = False,
                        watcher_interval: Optional[int] = 0,
                        access_user_ids: Optional[list[str]] = None, encrypt: bool = True) -> \
            Tuple[WildlandResult, Optional[WLTemplateFile]]:
        """
        Create a storage template.
        :param backend_type: storage type
        :param backend_params: params for the given backend, in the order listed by
        supported_storage_backends
        :param template_name: name of the template file to use; if exists, the template created will
        be appended to the file
        :param read_only: should the storage be read-only
        :param default_cache: mark template as default for container caches
        :param watcher_interval: set the storage watcher-interval in seconds
        :param access_user_ids: limit access to this storage to the provided users.
        Default: same as the container
        :param encrypt: should the storage manifest be encrypted. If this is False, access_user_ids
        should be None. In case of inline storages, container manifest itself might still be
        encrypted, this does not change its settings.
        :return: Tuple of WildlandResult and, if creation was successful, WLTemplate that was
        created
        """
        # TODO

    def template_list(self) -> Tuple[WildlandResult, List[WLTemplateFile]]:
        """
        List all known templates.
        :return: WildlandResult, List of WLTemplateFiles
        """
        # TODO

    def template_delete(self, template_name: str) -> WildlandResult:
        """
        Delete a template
        :param template_name: name of template to be deleted.
        """
        # TODO

    def template_export(self, template_name: str) -> Tuple[WildlandResult, Optional[str]]:
        """
        Return (if possible) contents of the provided template
        :param template_name: name of the template
        """
        # TODO

    def template_import(self, template_name: str, template_data: str) -> WildlandResult:
        """
        Import template from provided data.
        :param template_name: Name to be used for the template. If it exists, the contents
        will be replaced
        :param template_data: jinja template data
        """
        # TODO

    # FORESTS

    def forest_create(self, storage_template: str, user_id: str,
                      access_user_ids: Optional[List[str]] = None, encrypt: bool = True,
                      manifests_local_dir: Optional[str] = '/.manifests') -> WildlandResult:
        """
        Bootstrap a new forest
        :param storage_template: name of the template to be used for forest creation; must contain
        at least one writeable storage
        :param user_id: fingerprint of the user for whom the forest will be created
        :param access_user_ids: list of additional user fingerprints to encrypt the container to
        :param encrypt: if the container should be encrypted; mutually exclusive with
        access_user_ids
        :param manifests_local_dir: manifests local directory. Must be an absolute path
        :return: WildlandResult
        """
        # TODO

    # MOUNTING

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
        :param manifests_catalog: allow mounting containers from manifest catalogs
        :type manifests_catalog:
        :param callback: a function that takes WLContainer and will be called before each container
        mount
        :return: Tuple of WildlandResult, List of successfully mounted containers; WildlandResult
        contains the list of containers that were not mounted for various reasons (from errors to
        being already mounted)
        """
        # TODO

    def unmount_all(self) -> WildlandResult:
        """
        Unmount all mounted containers.
        """
        # TODO

    def unmount_by_mount_path(self, paths: List[str], include_children: bool = True) -> \
            WildlandResult:
        """
        Unmount mounted containers by mount paths
        :param paths: list of mount paths to unmount
        :param include_children: should subcontainers/children be unmounted (default: true)
        :return: WildlandResult
        """
        # TODO

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
        # TODO

    def mount_status(self) -> Tuple[WildlandResult, List[WLContainer]]:
        """
        List all mounted containers
        :return: tuple of WildlandResult and mounted WLContainers
        """
        # TODO
