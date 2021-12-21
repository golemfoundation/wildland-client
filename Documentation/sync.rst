Storage syncing
===============

Files can be synced between local and remote storages. Syncing is handled by storage backends
and (possibly) dedicated syncers. It relies on sha256 hash for checking for file changes and
verification of successful syncing.

Syncing will mirror changes between local and remote storages. If a conflict happens (e.g., on a
start, there are two files with the same name but different contents; or two storages modify the
same file at the same time) nothing will be changed in either place; the user can resolve conflict
manually via copying the desired file to the storage with the undesired file.

In order to achieve actual syncing, the storages must either have the watcher-interval parameter
in the manifest (which allows using a very naive watcher - one that scans the storage every
watcher-interval seconds and reports changes based on modification date) or a more efficient
watcher implementation. Furthermore, there can be plugins supporting more efficient types
of syncing between given backend types.

How to use
----------

Start syncing local storage and selected remote storage (by default the first listed in manifest).:

    wl container sync <container_name>

Stop syncing for a given container::

    wl container stop-sync <container_name>

Start syncing for a specified remote:

    wl container sync --target-storage <backend_id or storage_type> <container-name>

Perform a one-time sync between two specified storages (useful e.g. when migrating data from one
storage to another):

    wl container sync --target-storage <backend_id or storage_type> --source-storage <backend_id or storage_type> --one-shot <container-name>

Currently running sync jobs (and conflicts found) can be shown by::

    wl status

Development
-----------

Storage backend
---------------
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


Dedicated syncer
----------------
Dedicated storage syncers that can perform syncing more effectively for certain storages
can be implemented via Python's plugin mechanism. The syncers must use the `wildland.storage_sync`
entrypoint (see `setuptools` package) and inherit the `wildland.storage_sync.base.BaseSyncer` class.

* class parameters list the particular traits of a given syncer:

  * SOURCE_TYPES/TARGET_TYPES are lists of strings accepted as source/target StorageBackend.TYPE
    (a list consisting of a single "*" string means any storage syncer is accepted; syncers that
    match exactly are prioritized)
  * CONTINUOUS - can the syncer handle continuous syncing
  * ONE_SHOT - can the syncer handle one-shot syncing
  * UNIDIRECTIONAL - can the syncer handle syncing only in one direction, from source to target;
    all syncers are assumed to be able to handle bidirectional syncing
  * REQUIRES_MOUNT - does the syncer require storages to be mounted.
  * SYNCER_NAME is the internal name of the syncer.

* custom storage syncers must implement at least the iter_errors method, and:

  * if ONE_SHOT == True, they must support one_shot_sync
  * if CONTINUOUS == True, they must support start_sync, stop_sync and is_running methods.


Sync daemon
-----------

All sync jobs are run by the dedicated sync daemon (see `wildland.storage_sync.daemon`). This
daemon is built upon the `wildland.control_server.ControlServer` class, and works in a similar way
to the FUSE driver (see :doc:`FS driver </fuse-driver>`). It exposes a control interface over a Unix
socket and accepts JSON-encoded commands according to the schema defined in
``wildland/schemas/sync-commands.json``.

Command-line options:

* ``-b, --base-dir=DIR``: base directory for Wildland configuration.
* ``-l, --log-path=PATH``: log to a file (`-` means stderr), default: ~/.local/share/wildland/wl-sync.log
* ``-s, --socket-path=PATH``: listen on a given socket path, default is specified in the Wildland
  config (`sync-socket-path` value).
