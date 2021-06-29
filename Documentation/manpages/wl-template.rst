.. program:: wl-template
.. _wl-template:
.. _wl-template-create:
.. _wl-template-add:

************************************************************
:command:`wl template` - Storage template management
************************************************************

Synopsis
========

| :command:`wl template list [--show-filenames]`
| :command:`wl template create <storage_type> [<storage_params>] NAME`
| :command:`wl template add <storage_type> [<storage_params>] NAME`
| :command:`wl template remove NAME`

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

.. program:: wl-template-list
.. _wl-template-list:

:command:`wl template list [--show-filenames]`
------------------------------------------------------

Display known storage templates.

.. option:: --show-filenames, -s

    Show filenames.

.. program:: wl-template-remove
.. _wl-template-remove:

:command:`wl template remove NAME`
------------------------------------------

Delete a storage template from local filesystem.

.. program:: wl-template-create-bear-db
.. _wl-template-create-bear-db:

:command:`wl template create bear-db --path <absolute_path_to_sqlite_db> NAME`
--------------------------------------------------------------------------------------

.. include:: include/wl-template-create.rsti
.. include:: include/storages/bear.rsti

.. program:: wl-template-create-categorization
.. _wl-template-create-categorization:

:command:`wl template create categorization --reference-container-url <url> NAME`
-----------------------------------------------------------------------------------------

.. include:: include/wl-template-create.rsti
.. include:: include/storages/categorization.rsti

.. program:: wl-template-create-date-proxy
.. _wl-template-create-date-proxy:

:command:`wl template create date-proxy --reference-container-url <url> NAME`
-------------------------------------------------------------------------------------

.. include:: include/wl-template-create.rsti
.. include:: include/storages/date-proxy.rsti

.. program:: wl-template-create-delegate
.. _wl-template-create-delegate:

:command:`wl template create delegate --reference-container-url <url> NAME`
-----------------------------------------------------------------------------------

.. include:: include/wl-template-create.rsti
.. include:: include/storages/delegate.rsti

.. program:: wl-template-create-dropbox
.. _wl-template-create-dropbox:

:command:`wl template create dropbox --token <access_token> NAME`
-------------------------------------------------------------------------

.. include:: include/wl-template-create.rsti
.. include:: include/storages/dropbox.rsti

.. program:: wl-template-create-dummy
.. _wl-template-create-dummy:

:command:`wl template create dummy NAME`
------------------------------------------------

.. include:: include/wl-template-create.rsti

.. program:: wl-template-create-encrypted
.. _wl-template-create-encrypted:

:command:`wl template create encrypted --reference-container-url <url> NAME`
------------------------------------------------------------------------------------

.. include:: include/wl-template-create.rsti
.. include:: include/storages/encrypted.rsti

.. program:: wl-template-create-googledrive
.. _wl-template-create-googledrive:

:command:`wl template create googledrive --credentials <credentials> NAME`
----------------------------------------------------------------------------------

.. include:: include/wl-template-create.rsti
.. include:: include/storages/googledrive.rsti

.. program:: wl-template-create-http
.. _wl-template-create-http:

:command:`wl template create http --url <url> NAME`
-----------------------------------------------------------

.. include:: include/wl-template-create.rsti
.. include:: include/storages/http.rsti

.. program:: wl-template-create-imap
.. _wl-template-create-imap:

:command:`wl template create imap --host <host> --login <login> --password <password> NAME`
---------------------------------------------------------------------------------------------------

.. include:: include/wl-template-create.rsti
.. include:: include/storages/imap.rsti

.. program:: wl-template-create-gitlab
.. _wl-template-create-gitlab:

:command:`wl template create gitlab --personal-token <personal-token> NAME`
---------------------------------------------------------------------------

.. include:: include/wl-template-create.rsti
.. include:: include/storages/gitlab.rsti

.. program:: wl-template-create-ipfs
.. _wl-template-create-ipfs:

:command:`wl template create ipfs --ipfs-hash <url> --endpoint-address <multiaddress> NAME`
---------------------------------------------------------------------------------------------------

.. include:: include/wl-template-create.rsti
.. include:: include/storages/ipfs.rsti

.. program:: wl-template-create-local
.. _wl-template-create-local:

:command:`wl template create local --location <absolute_path> NAME`
---------------------------------------------------------------------------

.. include:: include/wl-template-create.rsti
.. include:: include/storages/local.rsti

.. program:: wl-template-create-local-cached
.. _wl-template-create-local-cached:

:command:`wl template create local-cached --location <absolute_path> NAME`
----------------------------------------------------------------------------------

.. include:: include/wl-template-create.rsti
.. include:: include/storages/local-cached.rsti

.. program:: wl-template-create-local-dir-cached
.. _wl-template-create-local-dir-cached:

:command:`wl template create local-dir-cached --location <absolute_path> NAME`
--------------------------------------------------------------------------------------

.. include:: include/wl-template-create.rsti
.. include:: include/storages/local-dir-cached.rsti

.. program:: wl-template-create-s3
.. _wl-template-create-s3:

:command:`wl template create s3 --s3-url <s3_url> --access-key <access_key> [--secret-key <secret_key>] NAME`
---------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-template-create.rsti
.. include:: include/storages/s3.rsti


.. program:: wl-template-create-sshfs
.. _wl-template-create-sshfs:

:command:`wl template create sshfs  [--sshfs-command <cmd>] --host <host> [--path <path>] [--ssh-user <user>] [--ssh-identity <path>|--pwprompt] [-mount-options <OPT1>[,OPT2,OPT3,...]] NAME`
----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-template-create.rsti
.. include:: include/storages/sshfs.rsti


.. program:: wl-template-create-static
.. _wl-template-create-static:

:command:`wl template create static [--file <path>=<content> ...] NAME`
-------------------------------------------------------------------------------

.. include:: include/wl-template-create.rsti
.. include:: include/storages/static.rsti

.. program:: wl-template-create-webdav
.. _wl-template-create-webdav:

:command:`wl template create webdav --url <url> --login <login> --password <password> NAME`
---------------------------------------------------------------------------------------------------

.. include:: include/wl-template-create.rsti
.. include:: include/storages/webdav.rsti

.. program:: wl-template-create-zip-archive
.. _wl-template-create-zip-archive:

:command:`wl template create zip-archive --location <absoute_path_to_zip_file> NAME`
--------------------------------------------------------------------------------------------

.. include:: include/wl-template-create.rsti
.. include:: include/storages/zip-archive.rsti

.. program:: wl-template-add-bear-db
.. _wl-template-add-bear-db:

:command:`wl template add bear-db --path <absolute_path_to_sqlite_db> NAME`
-----------------------------------------------------------------------------------

.. include:: include/wl-template-create.rsti
.. include:: include/storages/bear.rsti

.. program:: wl-template-add-categorization
.. _wl-template-add-categorization:

:command:`wl template add categorization --reference-container-url <url> NAME`
--------------------------------------------------------------------------------------

.. include:: include/wl-template-create.rsti
.. include:: include/storages/categorization.rsti

.. program:: wl-template-add-date-proxy
.. _wl-template-add-date-proxy:

:command:`wl template add date-proxy --reference-container-url <url> NAME`
----------------------------------------------------------------------------------

.. include:: include/wl-template-create.rsti
.. include:: include/storages/date-proxy.rsti

.. program:: wl-template-add-delegate
.. _wl-template-add-delegate:

:command:`wl template add delegate --reference-container-url <url> NAME`
--------------------------------------------------------------------------------

.. include:: include/wl-template-create.rsti
.. include:: include/storages/delegate.rsti

.. program:: wl-template-add-dropbox
.. _wl-template-add-dropbox:

:command:`wl template add dropbox --token <access_token> NAME`
----------------------------------------------------------------------

.. include:: include/wl-template-create.rsti
.. include:: include/storages/dropbox.rsti

.. program:: wl-template-add-dummy
.. _wl-template-add-dummy:

:command:`wl template add dummy NAME`
---------------------------------------------

.. include:: include/wl-template-create.rsti

.. program:: wl-template-add-encrypted
.. _wl-template-add-encrypted:

:command:`wl template add encrypted --reference-container-url <url> NAME`
---------------------------------------------------------------------------------

.. include:: include/wl-template-create.rsti
.. include:: include/storages/encrypted.rsti

.. program:: wl-template-add-googledrive
.. _wl-template-add-googledrive:

:command:`wl template add googledrive --credentials <credentials> NAME`
-------------------------------------------------------------------------------

.. include:: include/wl-template-create.rsti
.. include:: include/storages/googledrive.rsti

.. program:: wl-template-add-http
.. _wl-template-add-http:

:command:`wl template add http --url <url> NAME`
--------------------------------------------------------

.. include:: include/wl-template-create.rsti
.. include:: include/storages/http.rsti

.. program:: wl-template-add-imap
.. _wl-template-add-imap:

:command:`wl template add imap --host <host> --login <login> --password <password> NAME`
------------------------------------------------------------------------------------------------

.. include:: include/wl-template-create.rsti
.. include:: include/storages/imap.rsti

.. program:: wl-template-add-ipfs
.. _wl-template-add-ipfs:

:command:`wl template add ipfs --ipfs-hash <url> --endpoint-address <multiaddress> NAME`
------------------------------------------------------------------------------------------------

.. include:: include/wl-template-create.rsti
.. include:: include/storages/ipfs.rsti

.. program:: wl-template-add-local
.. _wl-template-add-local:

:command:`wl template add local --location <absolute_path> NAME`
------------------------------------------------------------------------

.. include:: include/wl-template-create.rsti
.. include:: include/storages/local.rsti

.. program:: wl-template-add-local-cached
.. _wl-template-add-local-cached:

:command:`wl template add local-cached --location <absolute_path> NAME`
-------------------------------------------------------------------------------

.. include:: include/wl-template-create.rsti
.. include:: include/storages/local-cached.rsti

.. program:: wl-template-add-local-dir-cached
.. _wl-template-add-local-dir-cached:

:command:`wl template add local-dir-cached --location <absolute_path> NAME`
-----------------------------------------------------------------------------------

.. include:: include/wl-template-create.rsti
.. include:: include/storages/local-dir-cached.rsti

.. program:: wl-template-add-s3
.. _wl-template-add-s3:

:command:`wl template add s3 --s3-url <s3_url> --access-key <access_key> [--secret-key <secret_key>] NAME`
------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-template-create.rsti
.. include:: include/storages/s3.rsti

.. program:: wl-template-add-sshfs
.. _wl-template-add-sshfs:

:command:`wl template add sshfs  [--sshfs-command <cmd>] --host <host> [--path <path>] [--ssh-user <user>] [--ssh-identity <path>|--pwprompt] [-mount-options <OPT1>[,OPT2,OPT3,...]] NAME`
-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

.. include:: include/wl-template-create.rsti
.. include:: include/storages/sshfs.rsti

.. program:: wl-template-add-static
.. _wl-template-add-static:

:command:`wl template add static [--file <path>=<content> ...] NAME`
----------------------------------------------------------------------------

.. include:: include/wl-template-create.rsti
.. include:: include/storages/static.rsti

.. program:: wl-template-add-webdav
.. _wl-template-add-webdav:

:command:`wl template add webdav --url <url> --login <login> --password <password> NAME`
------------------------------------------------------------------------------------------------

.. include:: include/wl-template-create.rsti
.. include:: include/storages/webdav.rsti

.. program:: wl-template-add-zip-archive
.. _wl-template-add-zip-archive:

:command:`wl template add zip-archive --location <absoute_path_to_zip_file> NAME`
-----------------------------------------------------------------------------------------

.. include:: include/wl-template-create.rsti
.. include:: include/storages/zip-archive.rsti

.. program:: wl-template-add-gitlab
.. _wl-template-add-gitlab:

:command:`wl template create gitlab --personal-token <personal-token> NAME`
---------------------------------------------------------------------------

.. include:: include/wl-template-create.rsti
.. include:: include/storages/gitlab.rsti
