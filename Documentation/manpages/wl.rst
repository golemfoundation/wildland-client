.. program:: wl
.. _wl:

:command:`wl` - CLI interface to Wildland
=========================================

Synopsis
--------

| :command:`wl [--base-dir <path>] [--debug] <subcommand> [...]`

Description
-----------

.. todo::

   TBD

Global options
--------------

.. option:: --verbose, -v

   Increase verbosity.

.. option:: --base-dir <path>

   Base directory for configuration. By default :file:`$HOME/.wildland`.

.. option:: --debug

   Display full backtraces on errors.

.. option:: --no-debug

   Hide backtraces on errors.

.. option:: --dummy

   Use dummy signatures.

.. option:: --no-dummy

   Do not use dummy signatures.

.. option:: --version

   Show version and exit.

Subcommands
-----------

:ref:`wl-version <wl-version>`

:ref:`wl-container <wl-container>`
:ref:`wl-storage <wl-storage>`
:ref:`wl-user <wl-user>`

:ref:`wl-sign <wl-sign>`
:ref:`wl-verify <wl-verify>`
:ref:`wl-edit <wl-edit>`
:ref:`wl-dump <wl-dump>`
:ref:`wl-publish <wl-publish>`
:ref:`wl-unpublish <wl-unpublish>`

:ref:`wl-start <wl-start>`
:ref:`wl-stop <wl-stop>`
:ref:`wl-status <wl-status>`
:ref:`wl-set-default-cache <wl-set-default-cache>`

:ref:`wl-get <wl-get>`
:ref:`wl-put <wl-put>`

Aliases
-------

Subcommands can be shortened to any unambiguous prefix. For example, instead of
:command:`wl container` you can write :command:`wl c`, and instead of
:command:`wl storage` you can write :command:`wl st` (but not :command:`wl s`,
because there is also :command:`wl sign`). Also there are some custom aliases,
like :command:`umount` in place of :command:`unmount` in a |~| couple of places.
Those are listed in `--help`.

Aliases are considered unstable (even the explicit ones, that are documented in
`--help`), should not be used when scripting, and are subject to change and
removal at any time (i.e., when adding new command, prefix may become
ambiguous).

See also
--------

:manpage:`fuse(8)`
