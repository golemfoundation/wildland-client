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

Display know storages.

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

.. program:: wl-storage-create-s3
.. _wl-storage-create-s3:

:command:`wl storage create s3 --container <container> [-u] [--user <user>] --bucket <bucket> <storage>`
--------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti

.. option:: --url <url>

   S3 URL, of the form ``s3://bucket/`` or ``s3://bucket/path/``. Required.

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
