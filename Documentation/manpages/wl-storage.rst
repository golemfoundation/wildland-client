.. program:: wl-storage
.. _wl-storage:
.. _wl-storage-create:

******************************************
:command:`wl storage` - Storage management
******************************************

Synopsis
========

| :command:`wl storage list`
| :command:`wl storage create <type> --container <container> [-u|-n] [--user <user>] [<type-specific-options>] <storage>`
| :command:`wl storage {sign|verify|edit} [...]`

Description
===========

.. todo::

   Write general description.

Commands
========

.. program:: wl-storage-list
.. _wl-storage-list:

:command:`wl storage list`
--------------------------

Display known storages.

.. program:: wl-storage-delete
.. _wl-storage-delete:

:command:`wl storage delete [--force] [--cascade] NAME`
-------------------------------------------------------

Delete a storage from local filesystem.

.. option:: --force, -f

   Delete even if the storage is used by containers. The containers in Widland
   directory (``~/.config/wildland/containers/``) will be examined.

.. option:: --cascade

   Delete the reference to storage from containers.

.. program:: wl-storage-create-local
.. _wl-storage-create-local:

:command:`wl storage create local --container <container> [-u] [--user <user>] --path <path> <storage>`
-------------------------------------------------------------------------------------------------------

Create local storage.

.. include:: include/wl-storage-create.rsti

.. option:: --path <path>

   Path to directory containing the backend. Required.

.. program:: wl_storage_create_local-cached
.. _wl_storage_create_local-cached:

:command:`wl storage create local-cached --container <container> [-u] [--user <user>] --path <path> <storage>`
--------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti

.. option:: --path <path>

.. program:: wl-storage-create-local-dir-cached
.. _wl-storage-create-local-dir-cached:

:command:`wl storage create local-dir-cached --container <container> [-u] [--user <user>] --path <path> <storage>`
------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti

.. option:: --path <path>

.. program:: wl-storage-create-date-proxy
.. _wl-storage-create-date-proxy:

:command:`wl storage create date-proxy --container <container> [-u] [--user <user>] --inner-container-url <url>  <storage>`
---------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti

.. option:: --inner-container-url <url>

   Inner container URL for this storage.

.. program:: wl-storage-create-zip-archive
.. _wl-storage-create-zip-archive:

:command:`wl storage create zip-archive --container <container> [-u] [--user <user>] --path <path>  <storage>`
-------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti

.. option:: --path <path>

   Path to ZIP archive.

.. program:: wl-storage-create-http-index
.. _wl-storage-create-http-index:

:command:`wl storage create http-index --container <container> [-u] [--user <user>] --url <url> <storage>`
----------------------------------------------------------------------------------------------------------

This is a HTTP storage that relies on directory listings. Currently used for buckets published using S3.

.. include:: include/wl-storage-create.rsti

.. option:: --url <url>

   HTTP URL.

.. program:: wl-storage-create-imap
.. _wl-storage-create-imap:
:command:`wl storage create imap --container <container> [-u] [--user <user>] --host <host> --login <login> --password <password> [--folder <folder>]`
--------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti

.. option:: --host <host>

   IMAP server hostname. Required.

.. option:: --login <login>

   IMAP account / login name. Required.

.. option:: --password <password>

   IMAP account password. Required.

.. option:: --folder <folder>

   IMAP folder to expose (defaults to INBOX).


.. program:: wl-storage-create-s3
.. _wl-storage-create-s3:
:command:`wl storage create s3 --container <container> [-u] [--user <user>] --url <url> <storage>`
--------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti

.. option:: --url <url>

   S3 URL, of the form ``s3://bucket/`` or ``s3://bucket/path/``. Required.

.. option:: --with-index

   Generate index pages. When this option is enabled, Wildland will maintain an
   `index.html` file with directory listing in every directory. These files
   will be invisible in the mounted filesystem, but they can be used to browse
   the S3 bucket when it's exposed using public HTTP.

.. program:: wl-storage-create-webdav
.. _wl-storage-create-webdav:

:command:`wl storage create webdav --container <container> [-u] [--user <user>] --url <url> --login <login> --password <password> <storage>`
--------------------------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti

.. option:: --url <url>

   Base URL for WebDAV resource. Required.

.. option:: --login <login>

   Login. Required.

.. option:: --password <password>

   Password. Required.

.. program:: wl-storage-create-bear-db
.. _wl-storage-create-bear-db:

:command:`wl storage create bear-db --container <container> [-u] [--user <user>] --path <path>`
-----------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti

.. option:: --path <path>

   Path to Bear SQLite database. Required.

.. option:: --with-content

   Serve also note content, not only manifests.

.. program:: wl-storage-create-bear-note
.. _wl-storage-create-bear-note:

:command:`wl storage create bear-note --container <container> [-u] [--user <user>] --path <path> --note <note>`
---------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti

.. option:: --path <path>

   Path to Bear SQLite database. Required.

.. option:: --note <note>

   Bear note identifier. Required.

.. _wl-storage-sign:
.. _wl-storage-verify:
.. _wl-storage-edit:

:command:`wl storage {sign|verify|edit} [...]`
----------------------------------------------

See :ref:`wl sign <wl-sign>`, :ref:`wl verify <wl-verify>`
and :ref:`wl edit <wl-edit>` documentation.
