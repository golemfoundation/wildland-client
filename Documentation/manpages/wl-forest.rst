.. program:: wl-forest
.. _wl-forest:

*************************************************
:command:`wl forest` - Forest management commands
*************************************************

Synopsis
========

| :command:`wl forest create <user> [<storage-set>]`
| :command:`wl forest mount []`
| :command:`wl forest unmount []`

Description
===========

These are commands to manage forests.

Commands
========

.. program:: wl-forest-create
.. _wl-forest-create:

:command:`wl forest create <user> [<storage-set>]`
--------------------------------------------------

Bootstrap a new Forest for given `<user>`.
You must have private key of that user in order to use this command.

Arguments:
| USER                  name of the user who owns the Forest (mandatory)
| STORAGE_SET           storage set used to create Forest containers, if not given, user's
|                       default storage-set is used instead

Description

This command creates an infrastructure container for the Forest
The storage set *must* contain a template with RW storage.

After the container is created, the following steps take place:

1. A link object to infrastructure container is generated and appended to USER's manifest.
2. USER manifest and infrastructure manifest are copied to the storage from Forest manifests container

.. option:: --access USER

   Allow an additional user access to containers created using this command. By default,
   those the containers are unencrypted unless at least one USER is passed using this option.

.. option:: --manifest-local-dir PATH

   Set manifests storage local directory. Must be an absolute path. Default: `/`


.. program:: wl-forest-mount
.. _wl-forest-mount:

:command:`wl forest mount <forest_name> [<forest_name>...]`
-----------------------------------------------------------

Mount a forest given by name or path to manifest.
The Wildland system has to be started first, see :ref:`wl start <wl-start>`.

.. program:: wl-forest-unmount
.. _wl-forest-unmount:

:command:`wl forest unmount <forest_name> [<forest_name>...]`
-------------------------------------------------------------

Unmount a forest given by name or path to manifest.