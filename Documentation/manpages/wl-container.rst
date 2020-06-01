.. program:: wl-container
.. _wl-container:

********************************************
:command:`wl container` - Container commands
********************************************

Synopsis
========

| :command:`wl container list`
| :command:`wl container create [--user <user>] --path <path> [--path <path2> ...]`
| :command:`wl container update [--storage <storage>] <container>`
| :command:`wl container mount []`
| :command:`wl container unmount`

Description
===========

.. todo::

   Write some general info about containers.

When the type of manifest is known, you can refer to a manifest just by a short
name (e.g. :command:`wl container sign C1` will know to look for
:file:`~/.config/wildland/containers/C1.yaml`).

Commands
========

.. program:: wl-container-list
.. _wl-container-list:

:command:`wl container list`
----------------------------

List known containers.

.. program:: wl-container-create
.. _wl-container-create:

:command:`wl container create [--user <user>] --path <path> [--path <path2> ...]`
---------------------------------------------------------------------------------

Create a |~| new container manifest.

.. option:: --path <path>

   The paths under which the container will be mounted.

.. option:: --user <user>

   The owner of the container.

   .. todo:: Write the config name for default user.

.. option:: -u, --update-user

   Add the container to the user manifest.

.. option:: -n, --no-update-user

   Don't add the container to the user manifest. This is the default.

.. program:: wl-container-update
.. _wl-container-update:

:command:`wl container update [--storage <storage>] <container>`
----------------------------------------------------------------

Update a |~| container manifest.

.. option:: --storage <storage>

   The storage to use.

   This option can be repeated.

.. program:: wl-container-mount
.. _wl-container-mount:

:command:`wl container mount <container>`
-----------------------------------------

Mount a container given by name or path to manifest. The Wildland system has to
be mounted first, see :ref:`wl mount <wl-mount>`.

.. program:: wl-container-unmount
.. _wl-container-unmount:

:command:`wl container unmount <container>`
-------------------------------------------

.. option:: --path <path>

   Mount path to search for.

.. _wl-container-sign:
.. _wl-container-verify:
.. _wl-container-edit:

:command:`wl container {sign|verify|edit} [...]`
------------------------------------------------------

See :ref:`wl sign <wl-sign>`, :ref:`wl verify <wl-verify>`
and :ref:`wl edit <wl-edit>` documentation.
