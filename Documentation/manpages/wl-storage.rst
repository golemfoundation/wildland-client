.. program:: wl-storage
.. _wl-storage:
.. _wl-storage-create:

******************************************
:command:`wl storage` - Storage management
******************************************

Synopsis
========

| :command:`wl {storage|storages} list`
| :command:`wl storage create <type> --container <container> [<type-specific-options>] <storage>`
| :command:`wl storage {sign|verify|edit} [...]`
| :command:`wl storage create-from-template --storage-template <storage_template> <container>`
| :command:`wl storage modify [--location <path>] [--add-access <user>] [--del-access <user>] <file>`
| :command:`wl storage publish <storage> [<storage> ...]`
| :command:`wl storage unpublish <storage> [<storage> ...]`

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

:command:`wl storage delete [--force] [--no-cascade] [--container <container>] NAME [NAME ...]`
-----------------------------------------------------------------------------------------------

Delete a storage from local filesystem.

.. option:: --force, -f

   Delete even if the storage is used by containers. The containers in Widland
   directory (``~/.config/wildland/containers/``) will be examined.

.. option:: --no-cascade

   Do not delete the reference to storage from containers.

.. option:: --container <container>

   Chose container from which the storage will be removed. (Required if NAME is ambiguous.)

.. program:: wl-storage-create-local
.. _wl-storage-create-local:

:command:`wl storage create local --container <container> [--manifest-pattern <glob>] [--subcontainer-manifest <path>] --location <filesystem_path> [--no-publish] <storage>`
--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

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

:command:`wl storage create local-cached --container <container> --location <filesystem_path> [--no-publish] <storage>`
-----------------------------------------------------------------------------------------------------------------------

Create cached local storage. See ``local`` storage description above for
details.

.. include:: include/wl-storage-create.rsti
.. include:: include/storages/local-cached.rsti

.. program:: wl-storage-create-local-dir-cached
.. _wl-storage-create-local-dir-cached:

:command:`wl storage create local-dir-cached --container <container> --location <filesystem_path> [--no-publish] <storage>`
---------------------------------------------------------------------------------------------------------------------------

Create directory cached local storage. See ``local`` storage description above
for details.

.. include:: include/wl-storage-create.rsti
.. include:: include/storages/local-dir-cached.rsti

.. program:: wl-storage-create-timeline
.. _wl-storage-create-timeline:

:command:`wl storage create timeline --container <container> --reference-container-url <url> [--timeline-root <dir>] [--no-publish] <storage>`
------------------------------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti
.. include:: include/storages/timeline.rsti

.. program:: wl-storage-create-delegate
.. _wl-storage-create-delegate:

:command:`wl storage create delegate --container <container> --reference-container-url <url> [--subdirectory <dir>] [--no-publish] <storage>`
---------------------------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti
.. include:: include/storages/delegate.rsti

.. program:: wl-storage-create-dummy
.. _wl-storage-create-dummy:

:command:`wl storage create dummy --container <container> [--no-publish]`
-------------------------------------------------------------------------

Creates dummy storage, presenting empty directory not backed by any actual data.

.. include:: include/wl-storage-create.rsti

.. program:: wl-storage-create-static
.. _wl-storage-create-static:

:command:`wl storage create static --container <container> [--file <path>=<content> ...] [--no-publish]`
--------------------------------------------------------------------------------------------------------

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

:command:`wl storage create zip-archive --container <container> --location <filesystem_path> [--no-publish] <storage>`
----------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti
.. include:: include/storages/zip-archive.rsti

.. program:: wl-storage-create-http
.. _wl-storage-create-http:

:command:`wl storage create http --container <container> --url <url> [--no-publish] <storage>`
----------------------------------------------------------------------------------------------

This is a HTTP storage that relies on directory listings. Currently used for buckets published using S3.

.. include:: include/wl-storage-create.rsti
.. include:: include/storages/http.rsti

.. program:: wl-storage-create-imap
.. _wl-storage-create-imap:

:command:`wl storage create imap --container <container> --host <host> --login <login> --password <password> [--folder <folder>] [--no-publish] <storage>`
----------------------------------------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti
.. include:: include/storages/imap.rsti

.. program:: wl-storage-create-dropbox
.. _wl-storage-create-dropbox:

:command:`wl storage create dropbox --container <container> --token <access_token> --app-key <app_key> [--refresh-token <refresh_token>] [--no-publish]`
--------------------------------------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti
.. include:: include/storages/dropbox.rsti

.. program:: wl-storage-create-categorization
.. _wl-storage-create-categorization:

:command:`wl storage create categorization --container <container> --reference-container-url <url> [--with-unclassified-category] [--unclassified-category-path <path>] [--no-publish] <storage>`
-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti
.. include:: include/storages/categorization.rsti

.. program:: wl-storage-create-transpose
.. _wl-storage-create-transpose:

:command:`wl storage create transpose --container <container> --reference-container-url <url> --rules <rules> --conflict <conflict> [--no-publish] <storage>`
-------------------------------------------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti
.. include:: include/storages/transpose.rsti

.. program:: wl-storage-create-googledrive
.. _wl-storage-create-googledrive:

:command:`wl storage create googledrive --container <container> --credentials <credentials> --skip-interaction [--no-publish]`
------------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti
.. include:: include/storages/googledrive.rsti

.. program:: wl-storage-create-s3
.. _wl-storage-create-s3:

:command:`wl storage create s3 --container <container> --url <url> <storage> [--no-publish]`
--------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti
.. include:: include/storages/s3.rsti

.. program:: wl-storage-create-sshfs
.. _wl-storage-create-sshfs:

:command:`wl storage create sshfs --container <container> [--sshfs-command <cmd>] --host <host> [--path <path>] [--ssh-user <user>] [--ssh-identity <path>|--pwprompt] [-mount-options <OPT1>[,OPT2,OPT3,...]]`
---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti
.. include:: include/storages/sshfs.rsti

.. program:: wl-storage-create-ipfs
.. _wl-storage-create-ipfs:

:command:`wl storage create ipfs --container <container> --ipfs-hash <url> --endpoint-addr <multiaddress> <storage> [--no-publish]`
-----------------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti
.. include:: include/storages/ipfs.rsti

.. program:: wl-storage-create-encrypted
.. _wl-storage-create-encrypted:

:command:`wl storage create encrypted --container <container> --reference-container-url <url> <storage>`
--------------------------------------------------------------------------------------------------------

Create encrypted storage for a given container. Please read details below to understand its limitations.

.. include:: include/wl-storage-create.rsti
.. include:: include/storages/encrypted.rsti


.. program:: wl-storage-create-webdav
.. _wl-storage-create-webdav:

:command:`wl storage create webdav --container <container> --url <url> --login <login> --password <password> <storage [--no-publish]`
-------------------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti
.. include:: include/storages/webdav.rsti

.. program:: wl-storage-create-bear-db
.. _wl-storage-create-bear-db:

:command:`wl storage create bear-db --container <container> --path <path> [--no-publish]`
-----------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti
.. include:: include/storages/bear.rsti

.. program:: wl-storage-create-gitlab
.. _wl-storage-create-gitlab:

:command:`wl storage create gitlab --container <container> [--server-url <url>] --personal-token <personal-token> --projectid <id> [--no-publish] <storage>`
------------------------------------------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti
.. include:: include/storages/gitlab.rsti

.. program:: wl-storage-create-gitlab-graphql
.. _wl-storage-create-gitlab-graphql:

:command:`wl storage create gitlab-graphql --container <container> --personal-token <personal-token> --project-path <path> [--no-publish] <storage>`
----------------------------------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti
.. include:: include/storages/gitlab-graphql.rsti

.. program:: wl-storage-create-jira
.. _wl-storage-create-jira:

:command:`wl storage create jira --container <container> --workspace-url <url> [--username <username>] [--personal-token <personal-token>] [--project-name <project-name>] [--limit <issues-limit>] <storage>`
---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti
.. include:: include/storages/jira.rsti

.. program:: wl-storage-create-git
.. _wl-storage-create-git:

:command:`wl storage create git --container <container> --url <url> [--username <username>] [--password <password>] [--no-publish] <storage>`
---------------------------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti
.. include:: include/storages/git.rsti

.. program:: wl-storage-create-redis
.. _wl-storage-create-redis:

:command:`wl storage create redis --container <container> --hostname <string> --database <int> [--password <string>] [--port 6379]`
-----------------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-create.rsti
.. include:: include/storages/redis.rsti

.. _wl-storage-sign:
.. _wl-storage-verify:
.. _wl-storage-edit:
.. _wl-storage-dump:

:command:`wl storage {sign|verify|edit} [...]`
----------------------------------------------

See :ref:`wl sign <wl-sign>`, :ref:`wl verify <wl-verify>`, :ref:`wl dump <wl-dump>`
and :ref:`wl edit <wl-edit>` documentation.


.. program:: wl-storage-create-from-template
.. _wl-storage-create-from-template:

:command:`wl storage create-from-template --storage-template <storage_template> <container>`
-----------------------------------------------------------------------------------------------

Create storages for a given container based on the storage template provided.

.. option:: --storage-template <storage_template>, --template, -t

   Storage template to use.

.. option:: --local-dir <local_dir>

    Local directory to be passed to storage templates as a parameter.

.. option:: --no-publish

   Do not publish the container after adding storage. By default, if the container owner has proper
   infrastructure defined in the user manifest, the container is published.

.. program:: wl-storage-modify
.. _wl-storage-modify:

:command:`wl storage modify [--location <path>] [--add-access <user>] [--del-access <user>] <file>`
---------------------------------------------------------------------------------------------------

Modify a storage |~| manifest given by *<file>*.

.. option:: --location

   Path to directory containing the backend.

.. option:: --add-access

   User or user path to add access for. Can be repeated.

.. option:: --del-access

   User to revoke access from. Can be repeated.

.. program:: wl-storage-publish
.. _wl-storage-publish:

:command:`wl storage publish <storage> [<storage> ...]`
-------------------------------------------------------

Publish storage manifests into user's manifests catalog (first container from the catalog
that provides read-write storage will be used).

.. program:: wl-storage-unpublish
.. _wl-storage-unpublish:

:command:`wl storage unpublish <storage> [<storage> ...]`
---------------------------------------------------------

Unpublish storage manifests from the whole of a user's manifests catalog.
