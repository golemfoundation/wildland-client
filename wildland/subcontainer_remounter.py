import time
from wildland.wildland_object.wildland_object import WildlandObject
from wildland.fs_client import WildlandFSClient
from wildland.client import Client
from wildland.container import Container, ContainerStub
from wildland.storage import Storage
from wildland.fs_client import WildlandFSClient, WatchEvent, WatchSubcontainerEvent
from wildland.storage_backends.watch import FileEventType
from .storage_backends.base import StorageBackend
from wildland.log import get_logger

logger = get_logger('subcontainer_remounter')

class SubcontainerRemounter:
    """
    """
    
    def __init__(self, client: Client, fs_client: WildlandFSClient,
                 container: WildlandObject.Type.CONTAINER, storage: Storage):
        self.container = container
        self.storage = storage
        self.client = client
        self.fs_client = fs_client
        
        self.to_mount: List[Tuple[Container,
                            Iterable[Storage],
                            Iterable[Iterable[PurePosixPath]],
                            Optional[Container]]] = []
        self.to_unmount: List[int] = []
        
        self.main_paths: Dict[PurePosixPath, PurePosixPath] = {}

        
#        self.backends = {}
#
#        for storage in storages:
#            backend = StorageBackend.from_params(storage.params, deduplicate=True)
#            get_children = backend.get_children(client = self.client)
#            self.backends[backend] = get_children
        

    def run(self):
        """
        Run the main loop.
        """
        
        while True:
            for events in self.fs_client.watch_subcontainers(self.storage.params, with_initial=True):
                for event in events:
                    self.handle_subcontainer_event(event)
                    
                self.unmount_pending()
                self.mount_pending()


    def handle_subcontainer_event(self, event: WatchSubcontainerEvent):
        """
        Handle a single file change event. Queue mount/unmount operations in
        self.to_mount and self.to_unmount.
        """
        logger.info('Event %s: %s', event.event_type, event.path)

        if event.event_type == FileEventType.DELETE:
            # Find out if we've already seen the file, and can match it to a
            # mounted storage.
            storage_id: Optional[int] = None
            if event.path in self.main_paths:
                storage_id = self.fs_client.find_storage_id_by_path(self.main_paths[event.path])

            # Stop tracking the file
            if event.path in self.main_paths:
                del self.main_paths[event.path]

            if storage_id is not None:
                logger.info('  (unmount %d)', storage_id)
                self.to_unmount.append(storage_id)
            else:
                logger.info('  (not mounted)')

        if event.event_type in [FileEventType.CREATE, FileEventType.MODIFY]:
            container = self.client.load_subcontainer_object(
                self.container, self.storage, event.subcontainer)

            # Start tracking the file
            self.main_paths[event.path] = self.fs_client.get_user_container_path(
                container.owner, container.paths[0])

            self.handle_changed_container(container)

    def handle_changed_container(self, container: Container):
        """
        Queue mount/remount of a container. This considers both new containers and
        already mounted containers, including changes in storages

        :param container: container to (re)mount
        :return:
        """
        user_paths = self.client.get_bridge_paths_for_user(container.owner)
        storages = self.client.get_storages_to_mount(container)
        if self.fs_client.find_primary_storage_id(container) is None:
            logger.info('  new: %s', str(container))
            self.to_mount.append((container, storages, user_paths, None))
        else:
            storages_to_remount = []

            for path in self.fs_client.get_orphaned_container_storage_paths(
                    container, storages):
                storage_id = self.fs_client.find_storage_id_by_path(path)
                assert storage_id is not None
                logger.info('  (removing orphan %s @ id: %d)', path, storage_id)
                self.to_unmount.append(storage_id)

            for storage in storages:
                if self.fs_client.should_remount(container, storage, user_paths):
                    logger.info('  (remounting: %s)', storage.backend_id)
                    storages_to_remount.append(storage)
                else:
                    logger.info('  (not changed: %s)', storage.backend_id)

            if storages_to_remount:
                self.to_mount.append((container, storages_to_remount, user_paths, None))
    
    def unmount_pending(self):
        """
        Unmount queued containers.
        """

        for storage_id in self.to_unmount:
            try:
                self.fs_client.unmount_storage(storage_id)
            except WildlandError as e:
                logger.error('failed to unmount storage %d: %s', storage_id, e)
        self.to_unmount.clear()

    def mount_pending(self):
        """
        Mount queued containers.
        """

        try:
            self.fs_client.mount_multiple_containers(self.to_mount, remount=True)
        except WildlandError as e:
            logger.error('failed to mount some storages: %s', e)
        self.to_mount.clear()
