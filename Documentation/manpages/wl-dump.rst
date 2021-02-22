.. program:: wl-dump
.. _wl-dump:

:command:`wl dump` - Dump (decrypted) manifest contents in a machine-readable way.
==================================================================================

Synopsis
--------

| wl dump [--decrypt/--no-decrypt] FILE

Description
-----------

The command will output manifest contents (without signature and by default decrypted)
in a machine-readable way.

If invoked with manifest type (:command:`wl user dump`, etc.), can also be used with short user/
container/etc names such as 'User'.

Options
--------

.. option:: -d, --decrypt

   Decrypt any encrypted fields, if possible. This is the default.

.. option:: -n, --no-decrypt

   Do not decrypt any encrypted fields.

