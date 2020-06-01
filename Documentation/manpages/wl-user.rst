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

You need to have a GPG private key in your keyring. You can create one using
:command:`gpg --gen-key` and answering interactive questions.

.. option:: --key <key>

Select available private key from local keyring by usual GPG convention (email,
name or even part of comment). This option is required.

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
