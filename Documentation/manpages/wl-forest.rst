.. program:: wl-forest
.. _wl-forest:

:command:`wl forest` - Forest management commands
=================================================

Synopsis
========

| :command:`wl forest create <user> [<storage-template>]`

Commands
========

.. program:: wl-forest-create
.. _wl-forest-create:

:command:`wl forest create <user> [<storage-template>]`
-------------------------------------------------------

Synopsis
--------

| Usage: wl forest create [OPTIONS] USER [STORAGE_TEMPLATE]

Description
-----------

Bootstrap a new Forest for given USER.
You must have private key of that user in order to use this command.

Arguments:
| USER                  name of the user who owns the Forest (mandatory)
| STORAGE_TEMPLATE      storage template used to create Forest containers

Description

This command creates an infrastructure container for the Forest
The storage template *must* contain at least one read-write storage.

After the container is created, the following steps take place:

1. A link object to infrastructure container is generated and appended to USER's manifest.
2. USER manifest and instracture manifest are copied to the storage from Forest manifests container

Options
--------

.. option:: --access USER

   Allow an additional user access to containers created using this command. By default,
   those the containers are unencrypted unless at least one USER is passed using this option.

.. option:: --manifest-local-dir PATH

   Set manifests storage local directory. Must be an absolute path. Default: `/`
