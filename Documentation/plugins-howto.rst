Plugins
=======

Implementing a plugin is a way to extend Wildland capabilities by adding a support for a new type of
:ref:`storage <wl-storage>`. Wildland exposes an API to register new storage drivers (a.k.a.
plugins). At the time of writing there are plugins for `Bear`_, `Dropbox`_, `IMAP`_, `IPFS`_, `S3`_
and `WebDAV`_.

.. _Bear: https://bear.app/
.. _Dropbox: https://en.wikipedia.org/wiki/Dropbox_(service)
.. _IMAP: https://en.wikipedia.org/wiki/Internet_Message_Access_Protocol
.. _IPFS: https://en.wikipedia.org/wiki/InterPlanetary_File_System
.. _S3: https://en.wikipedia.org/wiki/Amazon_S3
.. _WebDAV: https://en.wikipedia.org/wiki/WebDAV


API internals
-------------

All of the plugins live in their own installable Python modules, in ``plugins/`` directory. Each
plugin is self-contained and needs to implement some of the `filesystem operations`_, :ref:`manifest
<wl-manifests>` schema and command line argument handling for :ref:`wl storage create
<wl-storage-create>` command.

To add a new plugin, create a Python package and make sure it has a right entry point in
``setup.py``. A good way to start may be studying existing plugins.

.. _filesystem operations: https://libfuse.github.io/doxygen/structfuse__operations.html


.. _plugin-internals:


FUSE callbacks
~~~~~~~~~~~~~~

Wildland is built on top of `FUSE`_ (*Filesystem in Userspace*). To put it more precisely, FUSE
consists of a kernel module and a userspace ``libfuse`` library that abstracts away the `low-level
interface`_. Wildland directly utilizes `python-fuse`_ which is a Python interface to ``libfuse``.

.. image:: /_static/FUSE_structure.svg
   :width: 100%


Storage backend
~~~~~~~~~~~~~~~

Every plugin needs to implement :class:`~wildland.storage_backends.base.StorageBackend` which is an
abstract base class exposing an interface similar to the one being used by ``python-fuse``. The
following is the list of the methods you typically need to implement:

* :meth:`~wildland.storage_backends.base.StorageBackend.mount` - Called when :ref:`mounting a
  container <wl-container-mount>`. Initializes the storage, e.g. establishing a connection with a
  server.

* :meth:`~wildland.storage_backends.base.StorageBackend.unmount` - Called when :ref:`unmounting a
  container <wl-container-unmount>`. Cleans up the resources, e.g. closing a connection with a
  server.

* :meth:`~wildland.storage_backends.base.StorageBackend.open` - Based on the given ``path``,
  returns a :class:`~wildland.storage_backends.base.File` representing a file being opened. Object
  that is returned from this method wraps :meth:`~wildland.storage_backends.base.File.read` and
  :meth:`~wildland.storage_backends.base.File.write` operations amongst the others, therefore you
  typically shouldn't implement :class:`~wildland.storage_backends.base.StorageBackend`'s
  :meth:`~wildland.storage_backends.base.StorageBackend.read` and
  :meth:`~wildland.storage_backends.base.StorageBackend.write` which just call respective methods
  from :class:`~wildland.storage_backends.base.File` object.

  .. note::

    Typically you should not inherit directly from :class:`~wildland.storage_backends.base.File` as
    there are classes built on it to optimize read/writes by utilizing buffering. See:
    :class:`~wildland.storage_backends.zip_archive.FullBufferedFile` and
    :class:`~wildland.storage_backends.buffered.PagedFile`.

* :meth:`~wildland.storage_backends.base.StorageBackend.getattr` - Gets attributes of the given
  file: its size, timestamp and permissions. Returns :class:`~wildland.storage_backends.base.Attr`
  object or backend-specific one, inheriting from it (e.g.
  :class:`~plugins.dropbox.wildland_dropbox.backend.DropboxFileAttr`).

* :meth:`~wildland.storage_backends.base.StorageBackend.create` - Creates empty file with the given
  permissions.

* :meth:`~wildland.storage_backends.base.StorageBackend.unlink` - Removes (deletes) the given file.

* :meth:`~wildland.storage_backends.base.StorageBackend.mkdir` - Creates empty directory with
  given permissions.

* :meth:`~wildland.storage_backends.base.StorageBackend.rmdir` - Removes the given directory.
  This should succeed only if the directory is empty.

* :meth:`~wildland.storage_backends.base.StorageBackend.readdir` - Lists the given directory.

There are many other FUSE callbacks that, depending on the needs, you should or should not
implement. For full list, refer to :class:`~wildland.storage_backends.base.StorageBackend` class.

The following are examples of the classes inheriting from
:class:`~wildland.storage_backends.base.StorageBackend`. You can refer to them to see how they use
storage primitives.

* :class:`~wildland.storage_backends.local_cached.BaseCached` - Cached storage backed by local
  files.

* :class:`~wildland.storage_backends.date_proxy.DateProxyStorageBackend` - Proxy storage that
  re-organizes the files into directories based on their modification date.

* :class:`~wildland.storage_backends.delegate.DelegateProxyStorageBackend` - Proxy storage that
  exposes a subdirectory of another container.

* :class:`~wildland.storage_backends.encrypted.EncryptedStorageBackend` - Proxy storage that
  encrypts data and stores it in another container.

* :class:`~wildland.storage_backends.dummy.DummyStorageBackend` - Dummy storage.

* :class:`~wildland.storage_backends.local_cached.LocalCachedStorageBackend` - Cached storage that
  uses :meth:`~wildland.storage_backends.local_cached.LocalCachedStorageBackend.info_all`.

* :class:`~wildland.storage_backends.local_cached.LocalDirectoryCachedStorageBackend` - Cached
  storage that uses
  :class:`~wildland.storage_backends.local_cached.LocalDirectoryCachedStorageBackend.info_dir()`.

* :class:`~wildland.storage_backends.local.LocalStorageBackend` - Local, file-based storage.

* :class:`~wildland.storage_backends.zip_archive.ZipArchiveStorageBackend` - Read-only ZIP archive
  storage.

.. _FUSE: https://www.kernel.org/doc/Documentation/filesystems/fuse.txt
.. _low-level interface: https://man7.org/linux/man-pages/man4/fuse.4.html
.. _mixin: https://stackoverflow.com/questions/533631/what-is-a-mixin-and-why-are-they-useful
.. _python-fuse: https://github.com/libfuse/python-fuse


Command line and manifest
~~~~~~~~~~~~~~~~~~~~~~~~~

Besides the above mentioned methods that are all strictly related to handling filesystem operations,
you need to also implement:

* :meth:`~wildland.storage_backends.base.StorageBackend.cli_options`,
  :meth:`~wildland.storage_backends.base.StorageBackend.cli_create` that are responsible for parsing
  command line input.

* ``SCHEMA`` that defines storage :ref:`manifest <wl-manifests>` schema.


Storage Mixins
~~~~~~~~~~~~~~

Instead of implementing all of the FUSE callbacks yourself, you can use one of the `mixins`_
available. They provide higher abstraction primitives optimized for different scenarios.

The following is the list of all of the available mixins at the time of writing:

* :class:`~wildland.storage_backends.cached.DirectoryCachedStorageMixin` - Helps caching file's
  attributes and directory listings. It implements both
  :meth:`~wildland.storage_backends.base.StorageBackend.readdir` and
  :meth:`~wildland.storage_backends.base.StorageBackend.getattr` for you by utilizing a cache. You
  just need to implement
  :meth:`~wildland.storage_backends.cached.DirectoryCachedStorageMixin.info_dir` which is being used
  by both of those methods. Make sure to call
  :meth:`~wildland.storage_backends.cached.DirectoryCachedStorageMixin.clear_cache` whenever
  directory content or any of the files' attributes may change to not allow cache to serve outdated
  data.

* :class:`~wildland.storage_backends.cached.CachedStorageMixin` - Similar to
  :class:`~wildland.storage_backends.cached.DirectoryCachedStorageMixin` but caches whole storage
  instead of just a single directory. It implements both
  :meth:`~wildland.storage_backends.base.StorageBackend.readdir` and
  :meth:`~wildland.storage_backends.base.StorageBackend.getattr` for you by utilizing a cache. You
  just need to implement
  :meth:`~wildland.storage_backends.cached.DirectoryCachedStorageMixin.info_dir` which is being used
  by both of those methods. You should not use this mixin unless you are operating on relatively
  small tree directory.

* :class:`~wildland.storage_backends.generated.GeneratedStorageMixin` - Helps you with creating,
  auto-generated storage.
  :meth:`~wildland.storage_backends.generated.GeneratedStorageMixin.readdir`,
  :meth:`~wildland.storage_backends.generated.GeneratedStorageMixin.getattr`,
  :meth:`~wildland.storage_backends.generated.GeneratedStorageMixin.open` are implemented for you.
  You just need to implement
  :meth:`~wildland.storage_backends.generated.GeneratedStorageMixin.get_root` method. This mixin
  does not support cache (yet).

* :class:`~wildland.storage_backends.file_subcontainers.FileSubcontainersMixin` -
  Special type of mixin, providing support for subcontainers and infrastructure containers
  specified through flat file lists or glob expressions.

.. _mixins: https://stackoverflow.com/questions/533631/what-is-a-mixin-and-why-are-they-useful

Proxy backends
------------------

Sometimes you might want to utilize other storage backend from your own. Examples include
following classes, working with inner storage in very different ways.

* :class:`~wildland.storage_backends.delegate.DelegateProxyStorageBackend` - a simple and
  clean example, accesses inner storage directly.
* :class:`~wildland.storage_backends.date_proxy.DateProxyStorageBackend` - manipulates paths
  to create a `timeline` view of container contents.
* :class:`~wildland.storage_backends.encrypted.EncryptedStorageBackend` - utilizes access to
  inner storage directly and via FUSE.

When working with inner backend, consider what could the worst case look like. One example -
`encrypted` backend attempts to write down a configuration file for `gocryptfs` and does not
call `flush` to make sure that data is written to permanent storage. Since the inner storage is
`CachedStorageMixin`, few moments later `gocryptfs` attempts to read its configuration and fails.
A data race.


Installation
------------

To install your all of the plugins available, run:

.. code-block:: sh

  python3 -m venv env/
  . ./env/bin/activate
  pip install -r requirements.txt
  pip install -e . plugins/*

To check whether your newly implemented plugin was registered correctly, run:

.. code-block:: sh

  wl storage list
