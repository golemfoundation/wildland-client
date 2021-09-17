Internals
=========

Client interface
----------------

.. autoclass:: wildland.session.Session
   :members:

.. autoclass:: wildland.client.Client
   :members:

Storage backends
----------------

.. autoclass:: wildland.storage_backends.base.StorageBackend
   :members:

.. autoclass:: wildland.storage_backends.local_cached.BaseCached
   :members:

.. autoclass:: wildland.storage_backends.timeline.TimelineStorageBackend
   :members:

.. autoclass:: wildland.storage_backends.delegate.DelegateProxyStorageBackend
   :members:

.. autoclass:: plugins.encrypted.wildland_encrypted.backend.EncryptedStorageBackend
   :members:

.. autoclass:: wildland.storage_backends.dummy.DummyStorageBackend
   :members:

.. autoclass:: wildland.storage_backends.static.StaticStorageBackend
   :members:

.. autoclass:: wildland.storage_backends.local_cached.LocalCachedStorageBackend
   :members:

.. autoclass:: wildland.storage_backends.local_cached.LocalDirectoryCachedStorageBackend
   :members:

.. autoclass:: wildland.storage_backends.local.LocalStorageBackend
   :members:

.. autoclass:: wildland.storage_backends.http.HttpStorageBackend
   :members:


Syncing
-------

.. autoclass:: wildland.hashdb.HashCache
   :members:

.. autoclass:: wildland.storage_backends.watch.FileEvent
   :members:

.. autoclass:: wildland.storage_sync.base.SyncEvent
   :members:

.. autoclass:: wildland.storage_sync.base.SyncState
   :members:


File/dir entries
----------------

.. autoclass:: wildland.storage_backends.generated.CachedDirEntry
   :members:

.. autoclass:: wildland.storage_backends.generated.DirEntry
   :members:

.. autoclass:: wildland.storage_backends.generated.Entry
   :members:

.. autoclass:: wildland.storage_backends.generated.FileEntry
   :members:

.. autoclass:: wildland.storage_backends.generated.FuncDirEntry
   :members:

.. autoclass:: wildland.storage_backends.generated.FuncFileEntry
   :members:


Files
-----

.. autoclass:: wildland.storage_backends.base.File
   :members:

.. autoclass:: wildland.storage_backends.generated.CommandFile
   :members:

.. autoclass:: wildland.storage_backends.buffered.FullBufferedFile
   :members:

.. autoclass:: wildland.storage_backends.buffered.PagedFile
   :members:

.. autoclass:: wildland.storage_backends.generated.StaticFile
   :members:

.. autoclass:: wildland.storage_backends.generated.StaticFileEntry
   :members:

.. autoclass:: wildland.storage_backends.http.PagedHttpFile
   :members:


File attributes
---------------

.. autoclass:: wildland.storage_backends.base.Attr
   :members:

.. autoclass:: plugins.dropbox.wildland_dropbox.backend.DropboxFileAttr
   :members:


Mixins
------

.. autoclass:: wildland.storage_backends.cached.CachedStorageMixin
   :members:

.. autoclass:: wildland.storage_backends.cached.DirectoryCachedStorageMixin
   :members:

.. autoclass:: wildland.storage_backends.generated.GeneratedStorageMixin
   :members:

.. autoclass:: wildland.storage_backends.file_subcontainers.FileSubcontainersMixin
   :members:


Data transfer objects
---------------------

.. autoclass:: wildland.user.User
   :members:

.. autoclass:: wildland.container.Container
   :members:

.. autoclass:: wildland.container.ContainerStub
   :members:

.. autoclass:: wildland.storage.Storage
   :members:

.. autoclass:: wildland.bridge.Bridge
   :members:

.. autoclass:: wildland.link.Link
   :members:


Wildland path
-------------

.. autoclass:: wildland.wlpath.WildlandPath
   :members:

.. autoclass:: wildland.search.Search
   :members:

.. autoclass:: wildland.search.Step
   :members:


Manifests
---------

.. autoclass:: wildland.manifest.manifest.Manifest
   :members:

.. autoclass:: wildland.manifest.manifest.Header
   :members:

.. autoclass:: wildland.manifest.schema.Schema
   :members:

.. autoclass:: wildland.wildland_object.wildland_object.WildlandObject
   :members:

.. autoclass:: wildland.manifest.template.StorageTemplate
   :members:

.. autoclass:: wildland.manifest.template.TemplateFile
   :members:

.. autoclass:: wildland.manifest.template.TemplateManager
   :members:


Signing
-------

.. autoclass:: wildland.manifest.sig.SigContext
   :members:


FUSE driver
-----------

.. autoclass:: wildland.fs.WildlandFS
   :members:


Storage Driver
--------------
.. autoclass:: wildland.storage_driver.StorageDriver
   :members:
