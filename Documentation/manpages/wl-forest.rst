.. program:: wl-forest
.. _wl-forest:

:command:`wl forest` - Forest management commands
=================================================

Synopsis
========

| :command:`wl forest create <user> [<storage-set>] [<data-storage-set>]`

Commands
========

.. program:: wl-forest-create
.. _wl-forest-create:

:command:`wl forest create <user> [<storage-set>] [<data-storage-set>]`
-----------------------------------------------------------------------

Synopsis
--------

| Usage: wl forest create [OPTIONS] USER  [STORAGE_SET] [DATA_STORAGE_SET]

Description
-----------

Bootstrap a new Forest

Manifest storage set *must* contain a template with RW storage as well as
`base-url` parameter defined, which is used to determine the Forest's
infrastructure location.

Arguments:
|   USER              name of the user who owns the Forest (mandatory)
|   STORAGE_SET       storage set used to create Forest containers, if not given, user's
|                     default storage-set is used instead
|   DATA_STORAGE_SET  storage set used to create Forest data container, if not given, the
|                     STORAGE_SET is used instead

Options
--------

.. option:: --access USER

   Allow an additional user access to containers created using this command. By default,
   those the containers are unencrypted unless at least one USER is passed using this option.

.. option:: --manifest-local-dir PATH

   Set manifests storage local directory. Must be an absolute path. Default: `/`

.. option:: --data-local-dir PATH

   Set data storage local directory. Must be an absolute path. Default: `/`
