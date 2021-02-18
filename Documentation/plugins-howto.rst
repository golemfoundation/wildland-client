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


API Internals
-------------

All of the plugins live in their own installable Python modules, in ``plugins/`` directory. Each
plugin is self-contained and needs to implement some of the `filesystem operations`_, :ref:`manifest
<wl-manifests>` schema and command line argument handling for :ref:`wl storage create
<wl-storage-create>` command.

To add a new plugin, create a Python package, make sure it has a right entry point in ``setup.py``.
A good way to start may be studying existing plugins.

.. _filesystem operations: https://libfuse.github.io/doxygen/structfuse__operations.html


.. _plugin-internals:

FUSE callbacks
~~~~~~~~~~~~~~

Wildland is built on top of `FUSE`_ (*Filesystem in Userspace*). To put it more precisely, FUSE
consists of a kernel module and a userspace ``libfuse`` library that abstracts away the `low-level
interface`_. Wildland directly utilizes `python-fuse`_ which is a Python interface to ``libfuse``.

.. raw:: html

    <object data="../../img/FUSE_structure.svg" type="image/svg+xml"></object>

Every plugin needs to implement :class:`~wildland.storage_backends.base.StorageBackend` which is an
abstract base class exposing an interface similar to the one being used by ``python-fuse``. The
following is the list of the methods you typically need to implement:

* :meth:`~wildland.storage_backends.base.StorageBackend.mount` - Called when :ref:`mounting a
  container <wl-container-mount>`. Initializes the storage, e.g. establishing a connection with a
  server.

* :meth:`~wildland.storage_backends.base.StorageBackend.unmount` - Called when unmounting a
  storage. Cleans up the resources, e.g. closing a connection with a server.

* :meth:`~wildland.storage_backends.base.StorageBackend.open` - Based on the given ``path``,
  returns a :class:`~wildland.storage_backends.base.File` representing a file being opened. Object
  that is returned from this method wraps ``File.read`` and ``File.write`` operations amongst the
  others, therefore you typically shouldn't implement
  :class:`~wildland.storage_backends.base.StorageBackend`'s
  :meth:`~wildland.storage_backends.base.StorageBackend.read` and
  :meth:`~wildland.storage_backends.base.StorageBackend.write` which just call respective methods
  from :class:`~wildland.storage_backends.base.File` object.

  .. note::

    Typically you should not inherit directly from :class:`~wildland.storage_backends.base.File` as
    there are classes built on it to optimize read/writes by utilizing buffering. See:
    ``FullBufferedFile`` and ``PagedFile``.

* :meth:`~wildland.storage_backends.base.StorageBackend.getattr` - Gets attributes of the given
  file, like its size, timestamp, permissions.

* :meth:`~wildland.storage_backends.base.StorageBackend.create` - Creates empty file with given
  permissions.

* :meth:`~wildland.storage_backends.base.StorageBackend.unlink` - Removes (deletes) the given file.

* :meth:`~wildland.storage_backends.base.StorageBackend.mkdir` - Creates empty directory with
  given permissions.

* :meth:`~wildland.storage_backends.base.StorageBackend.rmdir` - Removes the given directory.
  This should succeed only if the directory is empty.

* :meth:`~wildland.storage_backends.base.StorageBackend.readdir` - Lists given directory.

There are many other FUSE callbacks that, depending on the needs, you should or should not
implement. For full list, refer to :class:`~wildland.storage_backends.base.StorageBackend` class.

Instead of using :class:`~wildland.storage_backends.base.StorageBackend` directly, you can use one
of the storage backends built on top of it:

* ``BaseCached``,
* ``LocalStorageBackend``,
* ``LocalCachedStorageBackend``,
* ``LocalDirectoryCachedStorageBackend``,
* ``DummyStorageBackend``,
* ``DateProxyStorageBackend``,
* ``DelegateProxyStorageBackend``,
* ``ZipArchiveStorageBackend``.

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

.. _directory-cached-storage-mixin:

* ``DirectoryCachedStorageMixin`` - Helps caching file's attributes and directory listings. It
  implements both :meth:`~wildland.storage_backends.base.StorageBackend.readdir` and
  :meth:`~wildland.storage_backends.base.StorageBackend.getattr` for you by utilizing a cache. You
  just need to implement ``DirectoryCachedStorageMixin.info_dir`` which is being used by both of
  those methods. Make sure to call ``DirectoryCachedStorageMixin.clear_cache`` whenever directory
  content or any of the files' attributes may change to not allow cache to serve outdated data.

* ``CachedStorageMixin`` - Similar to :ref:`DirectoryCachedStorageMixin
  <directory-cached-storage-mixin>` but caches whole storage instead of just a single directory. It
  implements both :meth:`~wildland.storage_backends.base.StorageBackend.readdir` and
  :meth:`~wildland.storage_backends.base.StorageBackend.getattr` for you by utilizing a cache. You
  just need to implement ``CachedStorageMixin.info_all`` which is being used by both of those
  methods. You should not use this mixin unless you are operating on relatively small tree
  directory.

* ``GeneratedStorageMixin`` - Helps you with creating, auto-generated storage. ``readdir``,
  ``getattr``, ``open`` are implemented for you. You just need to implement ``get_root`` method.
  This mixin does not support cache (yet).

* ``StaticSubcontainerStorageMixin`` - this is special type of mixin that is only applicable if you
  are working with :ref:`sub-containers <subcontainers>` (which is an experimental feature at the
  time of writing).

.. _mixins: https://stackoverflow.com/questions/533631/what-is-a-mixin-and-why-are-they-useful
