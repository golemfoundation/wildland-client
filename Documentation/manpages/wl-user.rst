.. program:: wl-user
.. _wl-user:

*************************************
:command:`wl user`: - User management
*************************************

Synopsis
========

| :command:`wl {user|users} list`
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

:command:`wl {user|users} list [OPTIONS]`
-----------------------------------------

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

.. option:: --add-pubkey <public_key>

   Add additional public key that can be used to verify manifests owned byt this user. The whole
   key must be specified. The key will be stored in a ``<fingerprint>.pub`` file in the key
   directory (``~/.config/wildland/keys``). Can be repeated.


.. program:: wl-user-delete
.. _wl-user-delete:

:command:`wl user delete [--force] [--cascade] [--delete-keys] NAME`
--------------------------------------------------------------------

Delete a user from local filesystem.

This will consider manifests in the local filesystem (stored in
``~/.config/wildland/``) signed by the user. However, it will not delete
locally stored key pairs (``~/.config/wildland/keys/``).

.. option:: --force, -f

   Delete even if there are manifests (containers/storage) signed by the user.

.. option:: --cascade

   Delete together with manifests (containers/storage) signed by the user.

.. option:: --delete-keys

   Delete together with public/private key pair owned by the user.

.. _wl-user-sign:
.. _wl-user-verify:
.. _wl-user-edit:

:command:`wl user {sign|verify|edit} [OPTIONS] <file>`
------------------------------------------------------

See help for :ref:`wl sign <wl-sign>`, :ref:`wl verify <wl-verify>` and
:ref:`wl edit <wl-edit>`.

.. program:: wl-user-import
.. _wl-user-import:

:command:`wl user import [--path path] [--bridge-owner user] [--only-first] url_or_path`
----------------------------------------------------------------------------------------

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

.. program:: wl-user-refresh
.. _wl-user-refresh:

:command:`wl user refresh USER`
----------------------------------------

Iterate over bridges and import all user manifest that those bridges refer to.
Note: This command will override the existing users' manifests.

Unless USER name is provided, the command will iterate over all bridges.
