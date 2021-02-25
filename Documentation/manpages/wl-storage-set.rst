.. program:: wl-storage-set
.. _wl-storage-set:

*******************************************************
:command:`wl storage-set` - Storage template management
*******************************************************

Synopsis
========

| :command:`wl storage-set list [--show-filenames]`
| :command:`wl storage-set add --template <template_file> --inline <storage_set>`
| :command:`wl storage-set del <storage_set>`
| :command:`wl storage-set set-default --user <user> <storage_set>`
| :command:`wl storage-set modify {add-template|del-template} [...] <storage_set>`

Description
===========

Storage templates and their sets are a convenient tool to easily create storage manifests for
containers.


Storage Templates
=================

Templates are jinja2 template files for .yaml storage manifests  (:ref: manifests)
located in `templates` directory in Wildland config directory (``~/.config/wildland/templates/``);
template files must have filenames ending with `.template.jinja`.

Templates can use the following parameters:
- `uuid`: container uuid
- `categories`: categories (you can use jinja syntax to extract only e.g.
first category: {{ categories|first }}
- `title`: container title
- `paths`: container paths (a list of PurePosixPaths)
- `local_path`: container local path (path to container file)

Manifest template should not contain `owner` and `container-path` fields - they are automatically
overwritten with correct values for a given container when the template is used.

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



Storage Sets
============

Storage sets are `.yaml` files located in `templates` directory in Wildland config directory
(``~/.config/wildland/templates/``). Storage set files must have filenames ending with
`.set.yaml`.They consist of a `name` field (with the name of the set) and `templates` field
with a list of template files (`file`) and their type for a given set (`file` for standalone
templates and `inline` for inline templates.

Sample storage set:

.. code-block:: yaml

    name: personal
    templates:
      - file: storage2.template.jinja
        type: standalone
      - file: storage1.template.jinja
        type: inline


Commands
========

.. program:: wl-storage-set-list
.. _wl-storage-set-list:

:command:`wl storage-set list [--show-filenames]`
-------------------------------------------------

Display known storage templates and storage sets.

.. option:: --show-filenames, -s

    Show filenames.

.. program:: wl-storage-set-remove
.. _wl-storage-set-remove:

:command:`wl storage-set remove NAME`
-------------------------------------

Delete a storage set from local filesystem.


.. program:: wl-storage-set-add
.. _wl-storage-set-add:

:command:`wl storage-set add --template <template_file> --inline <template_file> <storage_set>`
-----------------------------------------------------------------------------------------------

Create a storage set.

.. option:: --template <template_file>, -t

   Template file to include in the storage set as a standalone template.

.. option:: --inline <template_file>, -i

   Template file to include in the storage set as an inline template. At least one of this or
   --template is required.

.. program:: wl-storage-set-set-default
.. _wl-storage-set-set-default:

:command:`wl storage-set set-default --user <user> <storage_set>`
-----------------------------------------------------------------------------------------------

Specify a storage set to be used as default when creating new storages for the user's
containers.

.. option:: --user <user>

   User for which set the default.

.. program:: wl-storage-set-modify
.. _wl-storage-set-modify:

.. _wl-storage-set-modify-add-template:

:command:`wl storage-set modify add-template --template <template_file> --inline <template_file> <storage_set>`
---------------------------------------------------------------------------------------------------------------

Add templates to an existing set.

.. option:: --template <template_file>, -t

   Template file to add to the storage set as a standalone template.

.. option:: --inline <template_file>, -i

   Template file to add to the storage set as an inline template. At least one of this or
   --template is required.

.. _wl-storage-set-modify-del-template:

:command:`wl storage-set modify del-template --template <template_file> <storage_set>`
--------------------------------------------------------------------------------------

Remove templates from an existing set.

.. option:: --template <template_file>, -t

   Template file to be removed from the storage set. If the template file appears more than once,
   all of its occurrences will be removed.
