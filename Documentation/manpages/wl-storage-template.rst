.. program:: wl-storage-template
.. _wl-storage-template:
.. _wl-storage-template-create:

************************************************************
:command:`wl storage-template` - Storage template management
************************************************************

Synopsis
========

| :command:`wl storage-template list [--show-filenames]`
| :command:`wl storage-template create <storage_type> [<storage_params>] NAME`
| :command:`wl storage-template remove <storage_set>`

Description
===========

Storage templates and their sets are a convenient tool to easily create storage manifests for
containers.


Storage Templates
=================

Templates are jinja2 template files for .yaml storage manifests  (:ref: manifests)
located in `templates` directory in Wildland config directory (``~/.config/wildland/templates/``);
template files must have filenames ending with `.template.jinja`.

Template files can use the following variables in their jinja templates:
- `uuid`: container uuid
- `categories`: categories (you can use jinja syntax to extract only e.g.
first category: {{ categories|first }}
- `title`: container title
- `paths`: container paths (a list of PurePosixPaths)
- `local_path`: container local path (path to container file)

Warning: `title` and `categories` are optional and, if the container does not have them, will
not be passed to the template. Use jinja's {% if variable is defined %} syntax to check if they are
defined and provide reasonable defaults.

Sample very simple template for local storage:

.. code-block:: yaml

    path: /home/user/storage{{ paths|last }}
    type: local

Sample template using is defined syntax:

.. code-block:: yaml

    path: /home/user/storage/{% if title is defined -%} {{ title }} {% else -%} {{ uuid }} {% endif %}
    type: local

More complex example:

.. code-block:: yaml

    path: /home/user/storage/{% if categories is defined -%} {{ categories|first }} {% else -%} {{ (paths|last).relative_to('/') }} {% endif %}
    type: local



Commands
========

.. program:: wl-storage-template-list
.. _wl-storage-template-list:

:command:`wl storage-template list [--show-filenames]`
------------------------------------------------------

Display known storage templates.

.. option:: --show-filenames, -s

    Show filenames.

.. program:: wl-storage-template-remove
.. _wl-storage-template-remove:

:command:`wl storage-template remove [--force] [--cascade] NAME`
----------------------------------------------------------------

Delete a storage template from local filesystem. If attached to a storage set, you must use either
`--force` or `--cascade` to delete it. Note that you can't use both options simultaneously.

.. option:: --force

    Force removing storage template if attached to a set.

.. option:: --cascade

    Remove storage template along with all storage sets attached to it.


.. program:: wl-storage-template-create-local
.. _wl-storage-template-create-local:

:command:`wl storage-template create local --container <container> [-u] [--user <user>] [--subcontainer] --location <filesystem_path> <storage>`
------------------------------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti

.. include:: include/storages/local.rsti

.. program:: wl-storage-template-create-local-cached
.. _wl-storage-template-create-local-cached:

:command:`wl storage-template create local-cached --container <container> [-u] [--user <user>] --location <filesystem_path> <storage>`
--------------------------------------------------------------------------------------------------------------------------------------

Create cached local storage. See ``local`` storage description above for
details.

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/local-cached.rsti

.. program:: wl-storage-template-create-local-dir-cached
.. _wl-storage-template-create-local-dir-cached:

:command:`wl storage-template create local-dir-cached --container <container> [-u] [--user <user>] --location <filesystem_path> <storage>`
------------------------------------------------------------------------------------------------------------------------------------------

Create directory cached local storage. See ``local`` storage description above
for details.

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/local-dir-cached.rsti

.. program:: wl-storage-template-create-date-proxy
.. _wl-storage-template-create-date-proxy:

:command:`wl storage-template create date-proxy --container <container> [-u] [--user <user>] --reference-container-url <url> <storage>`
---------------------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/date-proxy.rsti

.. program:: wl-storage-template-create-delegate
.. _wl-storage-template-create-delegate:

:command:`wl storage-template create delegate --container <container> [-u] [--user <user>] --reference-container-url <url> [--subdirectory <dir>] <storage>`
------------------------------------------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/delegate.rsti

.. program:: wl-storage-template-create-dummy
.. _wl-storage-template-create-dummy:

:command:`wl storage-template create dummy --container <container> [-u] [--user <user>]`
----------------------------------------------------------------------------------------

Creates dummy storage, presenting empty directory not backed by any actual data.

.. include:: include/wl-storage-template-create.rsti

.. program:: wl-storage-template-create-zip-archive
.. _wl-storage-template-create-zip-archive:

:command:`wl storage-template create zip-archive --container <container> [-u] [--user <user>] --location <filesystem_path> <storage>`
-------------------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/zip-archive.rsti

.. program:: wl-storage-template-create-http-index
.. _wl-storage-template-create-http-index:

:command:`wl storage-template create http-index --container <container> [-u] [--user <user>] --url <url> <storage>`
-------------------------------------------------------------------------------------------------------------------

This is a HTTP storage that relies on directory listings. Currently used for buckets published using S3.

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/http-index.rsti

.. program:: wl-storage-template-create-imap
.. _wl-storage-template-create-imap:

:command:`wl storage-template create imap --container <container> [-u] [--user <user>] --host <host> --login <login> --password <password> [--folder <folder>] <storage>`
-------------------------------------------------------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/imap.rsti

.. program:: wl-storage-template-create-dropbox
.. _wl-storage-template-create-dropbox:

:command:`wl storage-template create dropbox --container <container> [-u] [--user <user>] --token <access_token>`
-----------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/dropbox.rsti

.. program:: wl-storage-template-create-categorization
.. _wl-storage-template-create-categorization:

:command:`wl storage-template create categorization --container <container> [-u] [--user <user>] --reference-container-url <url> <storage>`
-------------------------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/categorization.rsti

.. program:: wl-storage-template-create-s3
.. _wl-storage-template-create-s3:

:command:`wl storage-template create s3 --container <container> [-u] [--user <user>] --url <url> <storage>`
-----------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/s3.rsti

.. program:: wl-storage-template-create-ipfs
.. _wl-storage-template-create-ipfs:

:command:`wl storage-template create ipfs --container <container> [-u] [--user <user>] --ipfs-hash <url> --endpoint-address <multiaddress> <storage>`
-----------------------------------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/ipfs.rsti

.. program:: wl-storage-template-create-webdav
.. _wl-storage-template-create-webdav:

:command:`wl storage-template create webdav --container <container> [-u] [--user <user>] --url <url> --login <login> --password <password> <storage>`
-----------------------------------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/webdav.rsti

.. program:: wl-storage-template-create-bear-db
.. _wl-storage-template-create-bear-db:

:command:`wl storage-template create bear-db --container <container> [-u] [--user <user>] --path <path>`
--------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/bear.rsti
