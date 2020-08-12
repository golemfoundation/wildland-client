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
   ./wildland-fuse ./mnt -f -o log=-,socket=/tmp/wlfuse.sock

Mount a storage::

   echo '{ "cmd": "mount", "args": {"items": [{ "paths": ["/foo", "/bar"], "storage": {"type": "local", "path": "/tmp", "signer": "0xaaa"}}]}}' \
       | nc -U /tmp/wlfuse.sock

(Note that ``netcat-openbsd`` requires also the ``-N`` option to close
connection).

After you're done, unmount::

   fusermount -u ./mnt

Usually, you will not use the driver directly, but mount it using CLI (by
running ``wl start``).

Options
-------

Mount options (passed with ``-o``):

* ``log=PATH``: log to a file (`-` means stderr)
* ``breakpoint``: enable ``.control/breakpoint`` (see below)
* ``single_thread``: run FUSE in single-threaded mode
* ``socket=PATH``: listen on a given socket path

Control interface
-----------------

The driver exposes a control interface over a Unix socket. The socket is
intended to be used by Widland CLI.

Messages are passed using JSON. A JSON document has to end with two newlines
(``\\n\\n``), or end of stream (shutdown).

A **request** is a JSON message with the following keys:

* ``cmd`` - command name,
* ``args`` - a dictionary of command arguments, can be omitted if empty.

By convention, command name and arguments are all lower-case, with words
separated by dashes (``-``). This is the same as in Wildland manifests.

After processing a request (followed by two newlines, or EOF), the server sends
back a response.

A **response** can be a successful response or an error:

* A successful response contains a ``result`` field, with data returned by the
  command (or ``null`` if there is none).
* An error response contains an ``error`` dictionary, with ``class`` and
  ``desc`` fields.

Example request::

   { "cmd": "unmount", "args": { "storage_id": 1 }}

Example successful response::

   { "result": null }

Example error response::

   { "error": { "class": "WildlandError", "desc": "Storage not found" }}

To connect to control interface interactively (for debugging purposes), you can
use netcat::

   $ nc -U /path/to/wlfuse.sock
   { "cmd": "paths" }

After typing the request, followed by an empty line, you will see the result::

   { "result": "null" }

(Note that ``netcat-openbsd`` requires also the ``-N`` option to close
connection on local EOF).


Commands
^^^^^^^^

Here is a list of supported commands. A description like ``name(arg1, arg2,
arg3)`` specifies the following command::

    { "cmd": "name", "args": { "arg1": ..., "arg2": ..., "arg3": ... }}

The commands are currently implemented in ``wildland/fs.py``.

* ``paths()`` - return paths and corresponding storages, by number::

      {
        "/container1": [1],
        "/container2": [2, 3],
      }

* ``info()`` - return detailed storage information for each storage

* ``mount(items)`` mount storages. ``items`` is an array of items in the
  following format::

      {
        "paths": ["/path1", "/path2" ...],
        "remount": true,
        "extra": { ... },
        "storage": {
           "type": ...
           ...
        },
      }

  * ``paths``: list of absolute paths in Wildland namespace
  * ``storage``: parameters to be passed to storage backend
  * ``remount`` (optional):  if true, will also replace existing storage (as
    determined by the first path on the list)
  * ``extra`` (optional): extra data to be stored and returned by ``info``
  * ``read-only`` (optional): mount as read only

* ``unmount(storage-id)``- unmount a storage by number

* ``clear-cache(storage-id)`` - clear cache for a storage by number.
  This invalidates the cached data in storage. (The cache is currently very
  short-lived, so this endpoint is useful mostly for testing).

* ``clear-cache()`` - without arguments, will clear cache for all storages

* ``breakpoint()`` (write-only) - drop into debugger (``pdb``). This is enabled
  when the driver is running in foreground, and in single-thread mode
  (``wl start -d -S``).

  Be careful - while in debugger, access to the Wildland filesystem will be
  blocked, which may freeze other programs.
