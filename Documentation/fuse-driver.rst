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

After you're done, unmount:

   fusermount -u ./mnt

Options
-------

Command-line options for ``wildland-fuse``:

* ``-f``: make the driver run in foreground (you can't Ctrl-C it, though, you
  have to unmount)
* ``-d``: show debug information (implies ``-f``)

Mount options (passed with ``-o``):

* ``log=PATH``: log to a file (`-` means stderr)

Control interface
-----------------

There is a procfs-like interface under ``.control/``. It's intended to be used
by Widland CLI. Structured data is passed using JSON.

* ``.control/paths`` - paths and corresponding storages, by number::

      {
        "/.control": 0,
        "/container1": 1,
        "/container2": 2,
      }

* ``.control/storage/<NUM>`` - storage directories:

  * ``manifest.yaml`` - unsigned

* ``.control/mount`` (write-only) - mount a storage under a list of
  paths. Expects storage manifest fields under ``storage``::

      {
        "paths": ["/path1", "path2" ...],
        "storage": {
           "type": ...
           ...
        }
      }

* ``.control/unmount`` (write-only) - unmount a storage by number. Input data
  is a single number.
