.. program:: wl-user
.. _wl-user:

*************************************
:command:`wl user`: - User management
*************************************

Synopsis
========

| :command:`wl user list`
| :command:`wl user create <name> --key <key>`
| :command:`wl user {sign|verify} [...] <file>`
| :command:`wl user edit [--editor <editor>] <file>`

Description
===========

.. todo::

   Write general description about users.

Commands
========

.. program:: wl-user-list
.. _wl-user-list:

:command:`wl user list [OPTIONS]`
---------------------------------

List all known users.

.. program:: wl-user-create
.. _wl-user-create:

:command:`wl user create [OPTIONS] NAME`
----------------------------------------

Create a new user manifest and save it.

Unless ``--key`` is provided, the command will generate a new Signify key pair.

.. option:: --key <fingerprint>

Use an existing key pair to create a user. The key pair must be in the key
directory (``~/.config/wildland/keys``), as ``<fingerprint>.pub`` and
``<fingerprint>.sec`` files.

.. option:: --path <path>

Specify a path in Wildland namespace (such as ``/users/User``) for the
user. Can be repeated.

.. _wl-user-sign:
.. _wl-user-verify:
.. _wl-user-edit:

:command:`wl user {sign|verify|edit} [OPTIONS] <file>`
------------------------------------------------------

See help for :ref:`wl sign <wl-sign>`, :ref:`wl verify <wl-verify>` and
:ref:`wl edit <wl-edit>`.
