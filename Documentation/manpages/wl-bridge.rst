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
| :command:`wl bridge publish <bridge> [<bridge> ...]`
| :command:`wl bridge unpublish <bridge> [<bridge> ...]`

Description
===========

These are commands to manage bridge manifests.

Commands
========

.. program:: wl-bridge-create
.. _wl-bridge-create:

:command:`wl bridge create [--user USER] [--target-user USER] [--target-user-location URL-OR-PATH] [--path PATH] [--file-path FILE_PATH] [BRIDGE_NAME]`
-------------------------------------------------------------------------------------------------------------------------------------------------------

Create a new bridge manifest. At least one of --target-user and --target-user-location must be provided.

.. option:: --file-path FILE_PATH

   Create under a given path. By default, the manifest will be saved to the
   standard directory (``$HOME/.local/wildland/bridges/``).

.. option:: --owner USER

   User for signing.

.. option:: --target-user USER

   User which to whom the bridge is pointing. This must be an existing user in your wildland directory together with its pubkey.
   If this is provided and --target-user-location is skipped, an attempt to locate the user manifest
   in user's manifest catalog (under the canonical ``forest-owner.user.yaml`` form) will be made, and if
   this fails, local path to user manifest will be used.
   If this is omitted, user located at --target-user-location will be used.

.. option:: --target-user-location URL

   URL pointing to the user manifest to whom the bridge is pointing. If not provided, an attempt to
   locate either canonical user manifest in user's manifest catalog or user's local file path will
   be made.

.. option:: --path PATH

   Path for the user in Wildland namespace. Repeat for multiple paths.

   The paths override the paths in user manifest. If not provided, the paths
   will be copied from user manifest.


.. _wl-bridge-sign:
.. _wl-bridge-verify:
.. _wl-bridge-edit:
.. _wl-bridge-dump:

:command:`wl bridge> {sign|verify|edit} [...]`
----------------------------------------------

See :ref:`wl sign <wl-sign>`, :ref:`wl verify <wl-verify>`, :ref:`wl dump <wl-dump>`
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

Import a bridge. Accepts local paths to manifests, urls to manifests, Wildland urls
to manifests and Wildland urls to Wildland objects.

Note that the imported bridge owner will be the default-owner unless a different owner was passed
as the command option.

For Wildland object path, will import all referenced bridges and their reference users.

.. option:: --path

   Overwrite bridge paths with provided paths. Optional. Can be repeated. Works only if a single
   bridge is to imported (to avoid duplicate paths.

.. option:: --bridge-owner

    Override the owner of created bridge manifests with provided owner.

.. option:: --only-first

    Import only the first encountered bridge manifest. Ignored except for WL container paths.
    Particularly useful if --path is used.

.. program:: wl-bridge-publish
.. _wl-bridge-publish:

:command:`wl bridge publish <bridge> [<bridge> ...]`
----------------------------------------------------

Publish bridge manifests into user's manifests catalog (first container from the catalog
that provides read-write storage will be used).

.. program:: wl-bridge-unpublish
.. _wl-bridge-unpublish:

:command:`wl bridge unpublish <bridge> [<bridge> ...]`
------------------------------------------------------

Unpublish bridge manifests from the whole of a user's manifests catalog.
