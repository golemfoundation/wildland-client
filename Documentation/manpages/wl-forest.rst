.. program:: wl-forest
.. _wl-forest:

:command:`wl forest` - Forest management commands
=================================================

Synopsis
========

| :command:`wl forest create [--skip-bootstrap] <user> [<manifest-storage-set>] [<data-storage-set>]`

Commands
========

.. program:: wl-forest-create
.. _wl-forest-create:

:command:`wl forest create [--skip-bootstrap] <user> [<manifest-storage-set>] [<data-storage-set>]`
---------------------------------------------------------------------------------------------------

Synopsis
--------

| Usage: wl forest create [OPTIONS] USER
|        wl forest create [OPTIONS] USER MANIFEST_STORAGE_SET DATA_STORAGE_SET
|        wl forest create [OPTIONS] USER STORAGE_SET

Description
-----------

Bootstrap a new Forest

Manifest storage set *must* contain a template with RW storage as well as
`base-url` parameter defined, which is used to determine the Forest's
infrastructure location.

Arguments:
|   USER                  name of the user who owns the Forest (mandatory)
|   MANIFEST_STORAGE_SET  storage set used for Forest manifests container
|   DATA_STORAGE_SET      storage set used for Forest data container
|   STORAGE_SET           if passed, the same storage set is used for both
|                         manifests and data

Options
--------

.. option:: --access USER

   Allow an additional user access to this storage manifest. By default, storage manifests inherit
   access settings from the container.

.. option:: --manifest-container-owner USER

   Override manifest container owner. By default this vaule is equal to the Forest user.

.. option:: --data-container-owner USER

   Override data container owner. By default this vaule is equal to the Forest user.

.. option:: --manifest-local-dir PATH

   Set manifests storage local directory. Must be an absolute path. Default: `/`

.. option:: --data-local-dir PATH

   Set data storage local directory. Must be an absolute path. Default: `/`

.. option:: --skip-bootstrap

   Creates Forest containers but does not bootstrap the storage backend nor adds infrastructure
   to the Forest user. May be used by directory administrator who does not have Forest user'
   signing key.
