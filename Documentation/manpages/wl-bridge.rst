.. program:: wl-bridge
.. _wl-bridge:

**************************************
:command:`wl bridge` - Bridge commands
**************************************

Synopsis
========

| :command:`wl {bridge|bridges} list`
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

.. program:: wl-bridge-list
.. _wl-bridge-list:

:command:`wl {bridge|bridges} list`
-----------------------------------

List all known bridges.

.. program:: wl-bridge-import
.. _wl-bridge-import:

:command:`wl bridge import [--path path] [--bridge-owner user] [--only-first] url_or_path`
------------------------------------------------------------------------------------------

Import a user or bridge. Accepts local paths to manifests, urls to manifests, Wildland urls
to manifests and Wildland urls to Wildland objects.

For users, will import the user and create an appropriate bridge manifest referencing the user.
For bridge manifests, will import the bridge manifest and import the referenced user.

For Wildland object path, will import all referenced bridges and their reference users.

.. option:: --path

   Overwrite bridge paths with provided paths. Optional. Can be repeated. Works only if a single
   bridge is to imported (to avoid duplicate paths.

.. option:: --bridge-owner

    Override the owner of created bridge manifests with provided owner.

.. option:: --only-first

    Import only the first encountered bridge manifest. Ignored except for WL container paths.
    Particularly useful if --path is used.
