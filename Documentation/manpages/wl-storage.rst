.. program:: wl-storage
.. _wl-storage:

******************************************
:command:`wl storage` - Storage management
******************************************

Synopsis
========

| :command:`wl storage list`
| :command:`wl storage create <type> --container <container> [-u] [--user <user>] [<type-specific-options>] <storage>`
| :command:`wl storage {sign|verify|edit} [...]`

Description
===========

.. todo::

   Write general description.


.. program:: wl-storage-create
.. _wl-storage-create:

Common options for create commands
==================================

.. option:: --container <container>

   Choose container, for which the storage will be created. This option is
   required.

.. option:: --update-container, -u

   Update the container after creating storage.

.. option:: --user <user>

   User for signing.

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

.. option:: --path <path>

   Path to directory containing the backend. Required.

.. program:: wl-storage-create-local-cached
.. _wl-storage-create-local-cached:

:command:`wl storage create local-cached --container <container> [-u] [--user <user>] --path <path> <storage>`
--------------------------------------------------------------------------------------------------------------

.. option:: --path <path>

.. program:: wl-storage-create-s3
.. _wl-storage-create-s3:

:command:`wl storage create s3 --container <container> [-u] [--user <user>] --bucket <bucket> <storage>`
--------------------------------------------------------------------------------------------------------

.. option:: --bucket <bucket>

   S3 bucket. Required

.. program:: wl-storage-create-webdav
.. _wl-storage-create-webdav:

:command:`wl storage create webdav --container <container> [-u] [--user <user>] --url <url> --login <login> --password <password> <storage>`
--------------------------------------------------------------------------------------------------------------------------------------------

.. option:: --url <url>

   Base URL for WebDAV resource. Required.

.. option:: --login <login>

   Login. Required.

.. option:: --password <password>

   Password. Required.

.. _wl-storage-sign:
.. _wl-storage-verify:
.. _wl-storage-edit:

:command:`wl storage {sign|verify|edit} [...]`
----------------------------------------------

See :ref:`wl sign <wl-sign>`, :ref:`wl verify <wl-verify>`
and :ref:`wl edit <wl-edit>` documentation.
