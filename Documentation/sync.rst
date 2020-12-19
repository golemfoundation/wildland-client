Storage syncing
===============

Syncing of files between different storages is handled by storage backends and a coordinating
watcher mechanism. It relies on sha256 hash for checking for file changes and verification
of successful syncing.

Syncing will propagate changes in one storage to other storages. If a conflict happens (e.g., on a
start, there are two files with the same name but different contents; or two storages modify the
same file at the same time) nothing will be changed in either place; the user can resolve conflict
manually via copying the desired file to the storage with the undesired file.

In order to achieve actual syncing, the storages must either have the watcher-interval parameter
in the manifest (which allows using a very naive watcher - one that scans the storage every
watcher-interval seconds and reports changes based on modification date) or a more efficient
watcher implementation.

How to use
----------

Start syncing all backends of a given container::

    wl container sync <container_name>


Stop syncing for a given container::

    wl container stop-sync <container_name>


Development
-----------

The storage backend driver is responsible for:

* a more effective hashing/hash caching (through the get_hash method)
* a more efficient change-watching mechanism (through a class inheriting from StorageWatcher)
* an atomic compare-and-swap implementation (if possible; through the open_for_safe_replace() method)
* returning the StorageWatcher through the watcher() method (it's preferable to first check if
  there's no watcher-interval parameter in the manifest - see local.py implementation)
