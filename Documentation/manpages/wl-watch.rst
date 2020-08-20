.. program:: wl-watch
.. _wl-watch:

:command:`wl watch` --- Watch the Wildland filesystem for changes
=================================================================

Synopsis
--------

:command:`wl watch <pattern> [<pattern>...]`

Connect to the FUSE driver and watch for file changes. Use Ctrl-C to interrupt.

The patterns need to be absolute paths in the Wildland filesystem. Quote the
patterns to prevent shell from expanding them.

(This is a helper command for debugging. Run it with logging enabled
(``wl -vv watch``) to see more of the internals.)

.. option:: --with-initial

   Generate initial events (``create`` for the matched files) on command start.

Example
-------

::

   $ wl watch '/container/*.txt'
   create: /container/file1.txt
   create: /container/file2.txt
   modify: /container/file1.txt
   delete: /container/file2.txt
   ^C
   Aborted!
