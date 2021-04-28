.. program:: wl-storage
.. _wl-storage:
.. _wl-storage-create:

******************************************
:command:`wl storage` - Storage management
******************************************

Synopsis
========

| :command:`wl {storage|storages} list`
| :command:`wl storage create <type> --container <container> [-u|-n] [--user <user>] [<type-specific-options>] <storage>`
| :command:`wl storage {sign|verify|edit} [...]`
| :command:`wl storage create-from-set --storage-set <storage_set> <container>`
| :command:`wl storage modify {set-location} [...] <file>`

Description
===========

.. todo::

   Write general description.

Commands
========

.. program:: wl-storage-list
.. _wl-storage-list:

:command:`wl {storage|storages} list`
-------------------------------------

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

:command:`wl storage create local --container <container> [-u] [--user <user>] [--subcontainer] --location <filesystem_path> <storage>`
---------------------------------------------------------------------------------------------------------------------------------------

Create local storage.

A local storage refers to a directory on a local filesystem. To access a
directory, storage owner either needs to be listed in ``local-owners`` config
option, or in a ``.wildland-owners`` file in the directory (or any of it
parents). For example, to allow user ``0x123456`` to access files under
``/home/user/Dropbox``, create a ``/home/user/Dropbox/.wildland-owners`` file
with content like this:

   # empty lines and comments starting with '#' are ignored
   0x123456

.. include:: include/wl-storage-create.rsti
.. include:: include/storages/local.rsti

.. program:: wl-storage-create-local-cached
.. _wl-storage-create-local-cached:

:command:`wl storage create local-cached --container <container> [-u] [--user <user>] --location <filesystem_path> <storage>`
-----------------------------------------------------------------------------------------------------------------------------

Create cached local storage. See ``local`` storage description above for
details.

.. include:: include/wl-storage-create.rsti
.. include:: include/storages/local-cached.rsti

.. program:: wl-storage-create-local-dir-cached
.. _wl-storage-create-local-dir-cached:

:command:`wl storage create local-dir-cached --container <container> [-u] [--user <user>] --location <filesystem_path> <storage>`
---------------------------------------------------------------------------------------------------------------------------------

Create directory cached local storage. See ``local`` storage description above
for details.

.. include:: include/wl-storage-create.rsti
.. include:: include/storages/local-dir-cached.rsti

.. program:: wl-storage-create-date-proxy
.. _wl-storage-create-date-proxy:

:command:`wl storage create date-proxy --container <container> [-u] [--user <user>] --reference-container-url <url> <storage>`
------------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti
.. include:: include/storages/date-proxy.rsti

.. program:: wl-storage-create-delegate
.. _wl-storage-create-delegate:

:command:`wl storage create delegate --container <container> [-u] [--user <user>] --reference-container-url <url> [--subdirectory <dir>] <storage>`
---------------------------------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti
.. include:: include/storages/delegate.rsti

.. program:: wl-storage-create-dummy
.. _wl-storage-create-dummy:

:command:`wl storage create dummy --container <container> [-u] [--user <user>]`
-------------------------------------------------------------------------------

Creates dummy storage, presenting empty directory not backed by any actual data.

.. include:: include/wl-storage-create.rsti

.. program:: wl-storage-create-static
.. _wl-storage-create-static:

:command:`wl storage create static --container <container> [-u] [--user <user>] [--file <path>=<content> ...]`
--------------------------------------------------------------------------------------------------------------

Creates static storage, presenting files included directly in the storage manifest.

Example call::

    wl storage create static --container C1 --file 'foo.txt=content of foo.txt' --file 'foo/bar.txt=content of bar.txt inside foo directory'

This will result in storage manifest with the following field::

    content:
      foo.txt: content of foo.txt
      foo:
        bar.txt: content of bar.txt inside foo directory

.. include:: include/storages/static.rsti
.. include:: include/wl-storage-create.rsti

.. program:: wl-storage-create-zip-archive
.. _wl-storage-create-zip-archive:

:command:`wl storage create zip-archive --container <container> [-u] [--user <user>] --location <filesystem_path> <storage>`
----------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti
.. include:: include/storages/zip-archive.rsti

.. program:: wl-storage-create-http
.. _wl-storage-create-http:

:command:`wl storage create http --container <container> [-u] [--user <user>] --url <url> <storage>`
----------------------------------------------------------------------------------------------------

This is a HTTP storage that relies on directory listings. Currently used for buckets published using S3.

.. include:: include/wl-storage-create.rsti
.. include:: include/storages/http.rsti

.. program:: wl-storage-create-imap
.. _wl-storage-create-imap:

:command:`wl storage create imap --container <container> [-u] [--user <user>] --host <host> --login <login> --password <password> [--folder <folder>] <storage>`
----------------------------------------------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti
.. include:: include/storages/imap.rsti

.. program:: wl-storage-create-dropbox
.. _wl-storage-create-dropbox:

:command:`wl storage create dropbox --container <container> [-u] [--user <user>] --token <access_token>`
--------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti
.. include:: include/storages/dropbox.rsti

.. program:: wl-storage-create-categorization
.. _wl-storage-create-categorization:

:command:`wl storage create categorization --container <container> [-u] [--user <user>] --reference-container-url <url> [--with-unclassified-category] [--unclassified-category-path <path>] <storage>`
-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti
.. include:: include/storages/categorization.rsti

.. program:: wl-storage-create-googledrive
.. _wl-storage-create-googledrive:

:command:`wl storage create googledrive --container <container> [-u] [--user <user>] --credentials <credentials> --skip-interaction`
------------------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti

.. option:: --credentials <credentials>

   Google Drive Client Congifuration Object. You can generate it in Google Developer Console.
   More info: https://developers.google.com/drive/api/v3/quickstart/python#step_1_turn_on_the

.. option:: --skip-interaction

   Enable this optional flag if user passes authorization token object as credentials

.. program:: wl-storage-create-s3
.. _wl-storage-create-s3:

:command:`wl storage create s3 --container <container> [-u] [--user <user>] --url <url> <storage>`
--------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti
.. include:: include/storages/s3.rsti

.. program:: wl-storage-create-ipfs
.. _wl-storage-create-ipfs:

:command:`wl storage create ipfs --container <container> [-u] [--user <user>] --ipfs-hash <url> --endpoint-address <multiaddress> <storage>`
--------------------------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti
.. include:: include/storages/ipfs.rsti

.. program:: wl-storage-create-webdav
.. _wl-storage-create-webdav:

:command:`wl storage create webdav --container <container> [-u] [--user <user>] --url <url> --login <login> --password <password> <storage>`
--------------------------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti
.. include:: include/storages/webdav.rsti

.. program:: wl-storage-create-bear-db
.. _wl-storage-create-bear-db:

:command:`wl storage create bear-db --container <container> [-u] [--user <user>] --path <path>`
-----------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti
.. include:: include/storages/bear.rsti

.. _wl-storage-sign:
.. _wl-storage-verify:
.. _wl-storage-edit:
.. _wl-storage-dump:

:command:`wl storage {sign|verify|edit} [...]`
----------------------------------------------

See :ref:`wl sign <wl-sign>`, :ref:`wl verify <wl-verify>`, :ref:`wl dump <wl-dump>`
and :ref:`wl edit <wl-edit>` documentation.


.. program:: wl-storage-create-from-set
.. _wl-storage-create-from-set:

:command:`wl storage create-from-set --storage-set <storage_set> <container>`
-----------------------------------------------------------------------------------------------

Create storages for a given container based on the set provided.

.. option:: --storage-set <storage_set>, --set, -s

   Storage template set to use. If not specified, will use user's default set (if available)

.. option:: --local-dir <local_dir>

    Local directory to be passed to storage templates as a parameter.

.. program:: wl-storage-modify
.. _wl-storage-modify:

.. _wl-storage-modify-set-location:

:command:`wl storage modify set-location --location PATH <file>`
----------------------------------------------------------------

Set location in a storage |~| manifest given by *<file>*.

.. option:: --location

   Path to directory containing the backend.

.. _wl-storage-modify-add-access:

:command:`wl storage modify add-access --access USER <file>`
------------------------------------------------------------

Allow an additional user |~| access to manifest given by *<file>*.

.. option:: --access

   User to add access for. Can be repeated.

.. _wl-storage-modify-del-access:

:command:`wl storage modify del-acccess --access USER <file>`
-------------------------------------------------------------

Revoke user's |~| access to manifest given by *<file>*.

.. option:: --access

   User to revoke access from. Can be repeated.

