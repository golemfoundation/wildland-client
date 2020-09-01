.. program:: wl-bridge
.. _wl-bridge:

**************************************
:command:`wl bridge` - Bridge commands
**************************************

Synopsis
========

| :command:`wl bridge create`
| :command:`wl bridge edit`
| :command:`wl bridge sign`
| :command:`wl bridge verify`

Description
===========

These are commands to manage bridge manifests.

Commands
========

.. program:: wl-bridge-create
.. _wl-bridge-create:

:command:`wl bridge create [--user USER] --ref-user USER --ref-user-location URL-OR-PATH [--ref-user-path PATH] FILE_PATH`
--------------------------------------------------------------------------------------------------------------------------

Create a new bridge manifest under ``FILE_PATH``.

.. option:: --user USER

   User for signing.

.. option:: --ref-user USER

   User to refer to.

.. option:: --ref-user-location URL-OR-PATH

   Path to use for user manifest. This is either an URL, or a relative part
   (starting with ``./`` or ``../``).

.. option:: --ref-user-path PATH

   Path for the user in Wildland namespace. Repeat for multiple paths.

   The paths override the paths in user manifest. If not provided, the paths
   will be copied from user manifest.


.. _wl-bridge-sign:
.. _wl-bridge-verify:
.. _wl-bridge-edit:

:command:`wl bridge> {sign|verify|edit} [...]`
----------------------------------------------

See :ref:`wl sign <wl-sign>`, :ref:`wl verify <wl-verify>`
and :ref:`wl edit <wl-edit>` documentation.
