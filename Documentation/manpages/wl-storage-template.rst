.. program:: wl-storage-template
.. _wl-storage-template:
.. _wl-storage-template-create:
.. _wl-storage-template-add:

************************************************************
:command:`wl storage-template` - Storage template management
************************************************************

Synopsis
========

| :command:`wl storage-template list [--show-filenames]`
| :command:`wl storage-template create <storage_type> [<storage_params>] NAME`
| :command:`wl storage-template add <storage_type> [<storage_params>] NAME`
| :command:`wl storage-template remove NAME`

Description
===========

Storage templates are a convenient tool to easily create storage manifests for
containers.

The difference between `create` command and `add` commands is that `create` creates a new template
while `add` appends to an existing template.


Storage Templates
=================

Templates are jinja2 template files for .yaml storage manifests  (:ref: manifests)
located in `templates` directory in Wildland config directory (``~/.config/wildland/templates/``);
template files must have filenames ending with `.template.jinja`.

Template files can use the following variables in their jinja templates:

- `uuid`: container uuid
- `categories`: categories (you can use jinja syntax to extract only e.g. first category: {{ categories|first }}
- `title`: container title
- `paths`: container paths (a list of PurePosixPaths)
- `local_path`: container local path (path to container file)
- `owner`: container owner. Warning: you must encapsulate {{ owner }} variable in quotes, eg. '{{ owner }}'

Warning: `title` and `categories` are optional; thus, if the container does not have them, they will
not be passed to the template. Use jinja's {% if variable is defined %} syntax to check if they are
defined and provide reasonable defaults.

A few examples of basic storage templates:

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

:command:`wl storage-template remove NAME`
------------------------------------------

Delete a storage template from local filesystem.

.. program:: wl-storage-template-create-bear-db
.. _wl-storage-template-create-bear-db:

:command:`wl storage-template create bear-db --path <absolute_path_to_sqlite_db> NAME`
--------------------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/bear.rsti

.. program:: wl-storage-template-create-categorization
.. _wl-storage-template-create-categorization:

:command:`wl storage-template create categorization --reference-container-url <url> NAME`
-----------------------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/categorization.rsti

.. program:: wl-storage-template-create-date-proxy
.. _wl-storage-template-create-date-proxy:

:command:`wl storage-template create date-proxy --reference-container-url <url> NAME`
-------------------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/date-proxy.rsti

.. program:: wl-storage-template-create-delegate
.. _wl-storage-template-create-delegate:

:command:`wl storage-template create delegate --reference-container-url <url> NAME`
-----------------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/delegate.rsti

.. program:: wl-storage-template-create-dropbox
.. _wl-storage-template-create-dropbox:

:command:`wl storage-template create dropbox --token <access_token> NAME`
-------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/dropbox.rsti

.. program:: wl-storage-template-create-dummy
.. _wl-storage-template-create-dummy:

:command:`wl storage-template create dummy NAME`
------------------------------------------------

.. include:: include/wl-storage-template-create.rsti

.. program:: wl-storage-template-create-encrypted
.. _wl-storage-template-create-encrypted:

:command:`wl storage-template create encrypted --reference-container-url <url> NAME`
------------------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/encrypted.rsti

.. program:: wl-storage-template-create-googledrive
.. _wl-storage-template-create-googledrive:

:command:`wl storage-template create googledrive --credentials <credentials> NAME`
----------------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/googledrive.rsti

.. program:: wl-storage-template-create-http
.. _wl-storage-template-create-http:

:command:`wl storage-template create http --url <url> NAME`
-----------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/http.rsti

.. program:: wl-storage-template-create-imap
.. _wl-storage-template-create-imap:

:command:`wl storage-template create imap --host <host> --login <login> --password <password> NAME`
---------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/imap.rsti

.. program:: wl-storage-template-create-ipfs
.. _wl-storage-template-create-ipfs:

:command:`wl storage-template create ipfs --ipfs-hash <url> --endpoint-address <multiaddress> NAME`
---------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/ipfs.rsti

.. program:: wl-storage-template-create-local
.. _wl-storage-template-create-local:

:command:`wl storage-template create local --location <absolute_path> NAME`
---------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/local.rsti

.. program:: wl-storage-template-create-local-cached
.. _wl-storage-template-create-local-cached:

:command:`wl storage-template create local-cached --location <absolute_path> NAME`
----------------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/local-cached.rsti

.. program:: wl-storage-template-create-local-dir-cached
.. _wl-storage-template-create-local-dir-cached:

:command:`wl storage-template create local-dir-cached --location <absolute_path> NAME`
--------------------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/local-dir-cached.rsti

.. program:: wl-storage-template-create-s3
.. _wl-storage-template-create-s3:

:command:`wl storage-template create s3 --s3-url <s3_url> --access-key <access_key> [--secret-key <secret_key>] NAME`
---------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/s3.rsti

.. program:: wl-storage-template-create-static
.. _wl-storage-template-create-static:

:command:`wl storage-template create static [--file <path>=<content> ...] NAME`
-------------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/static.rsti

.. program:: wl-storage-template-create-webdav
.. _wl-storage-template-create-webdav:

:command:`wl storage-template create webdav --url <url> --login <login> --password <password> NAME`
---------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/webdav.rsti

.. program:: wl-storage-template-create-zip-archive
.. _wl-storage-template-create-zip-archive:

:command:`wl storage-template create zip-archive --location <absoute_path_to_zip_file> NAME`
--------------------------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/zip-archive.rsti

.. program:: wl-storage-template-add-bear-db
.. _wl-storage-template-add-bear-db:

:command:`wl storage-template add bear-db --path <absolute_path_to_sqlite_db> NAME`
-----------------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/bear.rsti

.. program:: wl-storage-template-add-categorization
.. _wl-storage-template-add-categorization:

:command:`wl storage-template add categorization --reference-container-url <url> NAME`
--------------------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/categorization.rsti

.. program:: wl-storage-template-add-date-proxy
.. _wl-storage-template-add-date-proxy:

:command:`wl storage-template add date-proxy --reference-container-url <url> NAME`
----------------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/date-proxy.rsti

.. program:: wl-storage-template-add-delegate
.. _wl-storage-template-add-delegate:

:command:`wl storage-template add delegate --reference-container-url <url> NAME`
--------------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/delegate.rsti

.. program:: wl-storage-template-add-dropbox
.. _wl-storage-template-add-dropbox:

:command:`wl storage-template add dropbox --token <access_token> NAME`
----------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/dropbox.rsti

.. program:: wl-storage-template-add-dummy
.. _wl-storage-template-add-dummy:

:command:`wl storage-template add dummy NAME`
---------------------------------------------

.. include:: include/wl-storage-template-create.rsti

.. program:: wl-storage-template-add-encrypted
.. _wl-storage-template-add-encrypted:

:command:`wl storage-template add encrypted --reference-container-url <url> NAME`
---------------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/encrypted.rsti

.. program:: wl-storage-template-add-googledrive
.. _wl-storage-template-add-googledrive:

:command:`wl storage-template add googledrive --credentials <credentials> NAME`
-------------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/googledrive.rsti

.. program:: wl-storage-template-add-http
.. _wl-storage-template-add-http:

:command:`wl storage-template add http --url <url> NAME`
--------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/http.rsti

.. program:: wl-storage-template-add-imap
.. _wl-storage-template-add-imap:

:command:`wl storage-template add imap --host <host> --login <login> --password <password> NAME`
------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/imap.rsti

.. program:: wl-storage-template-add-ipfs
.. _wl-storage-template-add-ipfs:

:command:`wl storage-template add ipfs --ipfs-hash <url> --endpoint-address <multiaddress> NAME`
------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/ipfs.rsti

.. program:: wl-storage-template-add-local
.. _wl-storage-template-add-local:

:command:`wl storage-template add local --location <absolute_path> NAME`
------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/local.rsti

.. program:: wl-storage-template-add-local-cached
.. _wl-storage-template-add-local-cached:

:command:`wl storage-template add local-cached --location <absolute_path> NAME`
-------------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/local-cached.rsti

.. program:: wl-storage-template-add-local-dir-cached
.. _wl-storage-template-add-local-dir-cached:

:command:`wl storage-template add local-dir-cached --location <absolute_path> NAME`
-----------------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/local-dir-cached.rsti

.. program:: wl-storage-template-add-s3
.. _wl-storage-template-add-s3:

:command:`wl storage-template add s3 --s3-url <s3_url> --access-key <access_key> [--secret-key <secret_key>] NAME`
------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/s3.rsti

.. program:: wl-storage-template-add-static
.. _wl-storage-template-add-static:

:command:`wl storage-template add static [--file <path>=<content> ...] NAME`
----------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/static.rsti

.. program:: wl-storage-template-add-webdav
.. _wl-storage-template-add-webdav:

:command:`wl storage-template add webdav --url <url> --login <login> --password <password> NAME`
------------------------------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/webdav.rsti

.. program:: wl-storage-template-add-zip-archive
.. _wl-storage-template-add-zip-archive:

:command:`wl storage-template add zip-archive --location <absoute_path_to_zip_file> NAME`
-----------------------------------------------------------------------------------------

.. include:: include/wl-storage-template-create.rsti
.. include:: include/storages/zip-archive.rsti
