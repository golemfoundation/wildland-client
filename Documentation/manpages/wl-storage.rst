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

.. option:: --location <filesystem_path>

   Path to directory containing the backend. Required.

.. option:: --subcontainer <filesystem_path>

   Relative path to a subcontainer manifest (can be repeated). Optional.

.. program:: wl_storage_create_local-cached
.. _wl_storage_create_local-cached:

:command:`wl storage create local-cached --container <container> [-u] [--user <user>] --location <filesystem_path> <storage>`
-----------------------------------------------------------------------------------------------------------------------------

Create cached local storage. See ``local`` storage description above for
details.

.. include:: include/wl-storage-create.rsti

.. option:: --location <filesystem_path>

.. program:: wl-storage-create-local-dir-cached
.. _wl-storage-create-local-dir-cached:

:command:`wl storage create local-dir-cached --container <container> [-u] [--user <user>] --location <filesystem_path> <storage>`
---------------------------------------------------------------------------------------------------------------------------------

Create directory cached local storage. See ``local`` storage description above
for details.

.. include:: include/wl-storage-create.rsti

.. option:: --location <filesystem_path>

.. program:: wl-storage-create-date-proxy
.. _wl-storage-create-date-proxy:

:command:`wl storage create date-proxy --container <container> [-u] [--user <user>] --reference-container-url <url>  <storage>`
-------------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti

.. option:: --reference-container-url <url>

   Inner container URL for this storage.

.. program:: wl-storage-create-delegate
.. _wl-storage-create-delegate:

:command:`wl storage create delegate --container <container> [-u] [--user <user>] --reference-container-url <url> [--subdirectory <dir>] <storage>`
---------------------------------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti

.. option:: --reference-container-url <url>

   Inner container URL for this storage.

.. option:: --subdirectory <path>

   Subdirectory within reference container. When set, content of this directory
   will be considered content of the container.

.. program:: wl-storage-create-zip-archive
.. _wl-storage-create-zip-archive:

:command:`wl storage create zip-archive --container <container> [-u] [--user <user>] --location <filesystem_path>  <storage>`
-----------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti

.. option:: --location <filesystem_path>

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

:command:`wl storage create imap --container <container> [-u] [--user <user>] --host <host> --login <login> --password <password> [--folder <folder>] <storage>`
----------------------------------------------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti

.. option:: --host <host>

   IMAP server hostname. Required.

.. option:: --login <login>

   IMAP account / login name. Required.

.. option:: --password <password>

   IMAP account password. Required.

.. option:: --folder <folder>

   IMAP folder to expose (defaults to INBOX).

.. option:: --ssl, --no-ssl

   Use SSL or unencrypted connection. Default is to use SSL.


.. program:: wl-storage-create-dropbox
.. _wl-storage-create-dropbox:

:command:`wl storage create dropbox --container <container> [-u] [--user <user>] --token <access_token>`
--------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti

.. option:: --token <access_token>

   Dropbox app token. You can generate it with Dropbox App Console.


.. program:: wl-storage-create-s3
.. _wl-storage-create-s3:

:command:`wl storage create s3 --container <container> [-u] [--user <user>] --url <url> <storage>`
--------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti

.. option:: --s3-url <url>

   S3 URL, of the form ``s3://bucket/`` or ``s3://bucket/path/``. Required.

.. option:: --endpoint-url <URL>

   Override default AWS S3 URL with the given URL.

.. option:: --with-index

   Generate index pages. When this option is enabled, Wildland will maintain an
   `index.html` file with directory listing in every directory. These files
   will be invisible in the mounted filesystem, but they can be used to browse
   the S3 bucket when it's exposed using public HTTP.


.. program:: wl-storage-create-ipfs
.. _wl-storage-create-ipfs:

:command:`wl storage create ipfs --container <container> [-u] [--user <user>] --ipfs-hash <url> --endpoint-address <multiaddress> <storage>`
--------------------------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti

.. option:: --ipfs-hash <URL>

   IPFS CID or IPNS name to access the resource, of the form ``/ipfs/CID`` or ``/ipns/name``. Required.

.. option:: --endpoint-addr <multiaddress>

   Override default IPFS gateway address (/ip4/127.0.0.1/tcp/8080/http) with the given address.


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

.. _wl-storage-sign:
.. _wl-storage-verify:
.. _wl-storage-edit:

:command:`wl storage {sign|verify|edit} [...]`
----------------------------------------------

See :ref:`wl sign <wl-sign>`, :ref:`wl verify <wl-verify>`
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
