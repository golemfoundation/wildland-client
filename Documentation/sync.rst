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

* a more efficient hashing algorithm (see get_hash in the StorageBackend class: it must return
  sha256 hash of the file)
* implementing get_file_token(path) method, which should return a string that identifies current
  state of the file (when the file contents change, the int should change, and vice versa) - it is
  used for caching hashes to avoid absurd amounts of computing and recomputing hash
* a more efficient change-watching mechanism (through a class inheriting from StorageWatcher)
* an atomic compare-and-swap implementation (if possible; through the open_for_safe_replace()
  method)
* returning the StorageWatcher through the watcher() method (it's preferable to first check if
  there's no watcher-interval parameter in the manifest - see local.py implementation)

Draft idea for extended storage syncing:

* Custom storage syncers should inherit the BaseSyncer class, implementing at least the start_sync,
  stop_sync, is_running and iter_errors methods. Optionally one_shot_sync, is_synced can be
  implemented
* Information about a given syncer is given through class params: SOURCE_TYPES/TARGET_TYPES is a
  list of strings accepted as source/target StorageBackend.TYPE (a list consisting of a single "*"
  string means any storage syncer is accepted; priority is given to syncers without "*"), ONE_SHOT,
  UNIDIRECTIONAL and REQUIRES_MOUNT specify whether the syncer can handle one_shot sync,
  unidirectional syncing and if it requires storages to be mounted, respectively.
* SYNCER_NAME can be used to enforce using a given syncer.
