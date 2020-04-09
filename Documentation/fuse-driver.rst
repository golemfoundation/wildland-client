FUSE Driver
===========

Quick start
-----------

Import the example GPG key::

   gpg2 --import example/test-public-key.key

Mount the filesystem::

   mkdir mnt
   ./wildland-fuse ./mnt -f \
      -o log=-,user_dir=./example/users,manifest=./example/manifests/container1.yaml,manifest=./example/manifests/container2.yaml

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
* ``dummy``: use dummy signature verification instead of GPG (for testing)
* ``user_dir=PATH``: load user manifests from a specific directory
* ``manifest=...`` (can be repeated): mount a container with given manifest
  (this is optional, you can also add containers afterwards using the
  ``.control`` system)

Control interface
-----------------

There is a procfs-like interface under ``.control/``:

* ``.control/paths`` - list of paths and corresponding containers, by number::

      /container1 0
      /container2 1
      /path/for/container1 0

* ``.control/containers/<NUM>`` - container directories:

  * ``manifest.yaml``
  * ``/storage/<NUM>/manifest.yaml``

* ``.control/cmd`` - commands (write-only file):

  * ``mount MANIFEST_FILE``
  * ``unmount MANIFEST_FILE``

* ``.control/mount`` - mount a manifest provided directly (``cat manifest.yaml >
  .control/mount``); note: absolute paths are required
