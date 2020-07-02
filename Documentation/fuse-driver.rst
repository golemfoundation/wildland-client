FUSE Driver
===========

The FUSE driver is a layer below Wildland CLI. It's responsible for mediating
between storage backends and the FUSE filesystem.

The driver intentionally does as little as possible. That means no signature
verification, no resolving containers/storages etc. See "Control interface" for
details.

Quick start
-----------
Mount the filesystem::

   mkdir mnt
   ./wildland-fuse ./mnt -f

Mount a storage::

   echo '{ "paths": ["/foo", "/bar"], "storage": {"type": "local", "path": "/tmp", "signer": "0xaaa"}}' \
       > ./mnt/.control/mount

After you're done, unmount::

   fusermount -u ./mnt

Usually, you will not use the driver directly, but mount it using CLI (by
running ``wl mount``).

Options
-------

Mount options (passed with ``-o``):

* ``log=PATH``: log to a file (`-` means stderr)
* ``breakpoint``: enable ``.control/breakpoint`` (see below)
* ``single_thread``: run FUSE in single-threaded mode

Control interface
-----------------

There is a procfs-like interface under ``.control/``. It's intended to be used
by Widland CLI.

Structured data is passed using JSON. However, a JSON document has to end with
two newlines (``\\n\\n``). This is so that we can handle large document spanning
multiple ``write()`` calls.

* ``.control/paths`` - paths and corresponding storages, by number::

      {
        "/.control": [0],
        "/container1": [1],
        "/container2": [2, 3],
      }

* ``.control/storage/<NUM>`` - storage directories:

  * ``manifest.yaml`` - unsigned

* ``.control/mount`` (write-only, JSON) - mount a storage under a list of
  paths. Expects storage manifest fields under ``storage``::

      {
        "paths": ["/path1", "path2" ...],
        "remount": true,
        "storage": {
           "type": ...
           ...
        }
      }

  (remember two newlines at the end)

  With ``remount`` set to true, will also replace existing storage (as
  determined by the first path on the list).

  Can be also passed an array of such commands.

* ``.control/unmount`` (write-only) - unmount a storage by number. Input data
  is a single number.

* ``.control/clear-cache`` (write-only) - clear cache for a storage by number.
  This invalidates the cached data in storage. (The cache is currently very
  short-lived, so this enpoint is useful mostly for testing).

* ``.control/breakpoint`` (write-only) - drop into debugger (``pdb``). This is
  enabled when the driver is running in foreground::

      $ wl mount -d

      # in another terminal:
      $ echo > ~/wildland/.control/breakpoint

  Be careful - while in debugger, access to the Wildland filesystem will be
  blocked, which may freeze other programs.
