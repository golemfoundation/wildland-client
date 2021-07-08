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

   mkdir wildland
   ./wildland-fuse ./wildland -f -o log=-,socket=/tmp/wlfuse.sock

Mount a storage::

   echo '{ "cmd": "mount", "args": {"items": [{ "paths": ["/foo", "/bar"], "storage": {"type": "local", "path": "/tmp", "owner": "0xaaa"}}]}}' \
       | nc -U /tmp/wlfuse.sock

(Note that ``netcat-openbsd`` requires also the ``-N`` option to close
connection).

After you're done, unmount::

   fusermount -u ./wildland

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
* ``args`` (optional) - a dictionary of command arguments, can be omitted if
  empty,
* ``id`` (optional) - a request ID.

By convention, command name and arguments are all lower-case, with words
separated by dashes (``-``). This is the same as in Wildland manifests.

After processing a request (followed by two newlines, or EOF), the server sends
back a response.

A **response** can be a successful response or an error:

* A successful response contains a ``result`` field, with data returned by the
  command (or ``null`` if there is none).
* An error response contains an ``error`` dictionary, with ``class`` and
  ``desc`` fields.

If the request contains an ``id`` field, the corresponding response will
contain an ``id`` field with the same value.

Example request::

   { "cmd": "unmount", "args": { "storage_id": 1 }, "id": 123 }

Example successful response::

   { "result": null, "id": 123 }

Example error response::

   { "error": { "class": "WildlandError", "desc": "Storage not found" }, "id": 123 }

To connect to control interface interactively (for debugging purposes), you can
use netcat::

   $ nc -U /path/to/wlfuse.sock
   { "cmd": "paths" }

After typing the request, followed by an empty line, you will see the result::

   { "result": "null" }

(Note that ``netcat-openbsd`` requires also the ``-N`` option to close
connection on local EOF).

Events
^^^^^^

The server can also send asynchronous events sent by the server, if the user
subscribes to them. In such case, when receiving messages, you must be prepared
to receive an event before the command response.

An event message is a JSON message with ``event`` field.

Commands
^^^^^^^^

Here is a list of supported commands, with their arguments.

The commands are currently implemented in ``wildland/fs_base.py``. The
arguments are validated, see ``wildland/schemas/fs-commands.json``.

* ``paths`` - return paths and corresponding storages, by number::

      {
        "/container1": [1],
        "/container2": [2, 3],
      }

  .. schema:: fs-commands.json args paths


* ``info`` - return detailed storage information for each storage

  .. schema:: fs-commands.json args info

* ``mount`` - mount storages

  .. schema:: fs-commands.json args mount

  Example ``items`` array::

      {
        "paths": ["/path1", "/path2" ...],
        "remount": true,
        "extra": { ... },
        "storage": {
           "type": ...
           ...
        },
      }


* ``unmount``- unmount a storage by number

  .. schema:: fs-commands.json args unmount


* ``clear-cache`` - clear cache for a storage by number. This invalidates the
  cached data in storage. (The cache is currently very short-lived, so this
  endpoint is useful mostly for testing).

  .. schema:: fs-commands.json args clear-cache

* ``breakpoint`` - drop into debugger (``pdb``). This is enabled
  when the driver is running in foreground, and in single-thread mode
  (``wl start -d -S``).

  .. schema:: fs-commands.json args breakpoint

  Be careful - while in debugger, access to the Wildland filesystem will be
  blocked, which may freeze other programs.

* ``add-watch`` - watch for changes to files in a storage.
  The pattern is a glob-style pattern, such as ``*/container.yaml``. It has to
  be relative and is interpreted in the context of the storage.

  .. schema:: fs-commands.json args add-watch

  The result is an integer watch ID.

  After adding a watch, the server will send a list of events whenever a file
  or directory matching the pattern is changed, for example::

      [{
        "type": "create",
        "path": "path/to/file",
        "storage-id": 1,
        "watch-id": 123
      }]

  The event type can be ``create``, ``delete`` or ``modify``.

  Note that unless the storage backend provides special support, the FUSE
  driver will report only locally originated changes, not changes to underlying
  storage (e.g. made from another device).
