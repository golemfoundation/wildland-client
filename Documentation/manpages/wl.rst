.. program:: wl
.. _wl:

:command:`wl` - CLI interface to Wildland
=========================================

Synopsis
--------

| :command:`wl [--base-dir <path>] <subcommand> [...]`

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

.. option:: --dummy

   Use dummy signatures.

.. option:: --no-dummy

   Do not use dummy signatures.

.. option:: --version

   Show version and exit.

Subcommands
-----------

:ref:`wl-container <wl-container>`
:ref:`wl-storage <wl-storage>`
:ref:`wl-user <wl-user>`

:ref:`wl-sign <wl-sign>`
:ref:`wl-verify <wl-verify>`
:ref:`wl-edit <wl-edit>`

:ref:`wl-mount <wl-mount>`
:ref:`wl-unmount <wl-unmount>`

:ref:`wl-get <wl-get>`
:ref:`wl-put <wl-put>`

See also
--------

:manpage:`fuse(8)`
