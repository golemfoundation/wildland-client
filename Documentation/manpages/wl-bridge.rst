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

:command:`wl bridge create [--user USER] --ref-user USER --ref-user-location URL-OR-PATH [--ref-user-path PATH] [--file-path FILE_PATH] [BRIDGE_NAME]`
------------------------------------------------------------------------------------------------------------------------------------------------------

Create a new bridge manifest. Either ``BRIDGE_NAME`` or ``--file-path`` needs
to be provided.

.. option:: --file-path FILE_PATH

   Create under a given path. By default, the manifest will be saved to the
   standard directory (``$HOME/.local/wildland/bridges/``).

.. option:: --owner USER

   User for signing.

.. option:: --ref-user USER

   User which to whom the bridge is pointing. This must be an existing user in your wildland directory together wtith its pubkey.
   This field is optional but recommended to use instead of relying solely on --ref-user-location.

.. option:: --ref-user-location URL

   URL pointing to the user manifest to whom the bridge is pointing. If ref-user user is skipped, this manifest will be fetched instead
   and considered trusted.

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
