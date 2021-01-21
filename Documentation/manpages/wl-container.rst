.. program:: wl-container
.. _wl-container:

********************************************
:command:`wl container` - Container commands
********************************************

Synopsis
========

| :command:`wl container list`
| :command:`wl container create [--user <user>] --path <path> [--path <path2> ...] [--storage-set <storage_set>]`
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

.. program:: wl-container-delete
.. _wl-container-delete:

:command:`wl container delete [--force] [--cascade] NAME`
---------------------------------------------------------

Delete a container from local filesystem.

.. option:: --force, -f

   Delete even if the container refers to local storage manifests.

.. option:: --cascade

   Delete together with all local storage manifests.

.. program:: wl-container-create
.. _wl-container-create:

:command:`wl container create [--user <user>] --path <path> [--path <path2> ...] [--storage-set <storage-set>]`
---------------------------------------------------------------------------------------------------------------

Create a |~| new container manifest.

.. option:: --path <path>

   The paths under which the container will be mounted.

.. option:: --user <user>

   The owner of the container.

   .. todo:: Write the config name for default user.

.. option:: --title <title>

    Title of the container. Used when generating paths based on categories.

.. option:: --category </path/to/category>

    Category to use in generating paths. Requires --title. May be provided multiple times.

.. option:: -u, --update-user

   Add the container to the user manifest.

.. option:: -n, --no-update-user

   Don't add the container to the user manifest. This is the default.

.. option:: --storage-set <storage_set>, --set

   Create storages for a container with a given storage-set.

.. option:: --local-dir <local_dir>

    Local directory to be passed to storage templates as a parameter. Requires --storage-set.

.. option:: --default-storage-set

    Use default storage set for the user, if available.

.. option:: --no-default-storage-set

    Do not use default storage set for the user, even if available.


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

:command:`wl container mount [--quiet/-q] [--remount/--no-remount] [--with-subcontainers/--without-subcontainers] [--only-subcontainers] <container> [<container>...]`
----------------------------------------------------------------------------------------------------------------------------------------------------------------------

Mount a container given by name or path to manifest. The Wildland system has to
be mounted first, see :ref:`wl start <wl-start>`.

.. option:: -r, --remount

   Replace the container currently mounted, if any. The container is identified
   by its first path.

.. option:: -n, --no-remount

   Don't replace existing container. If the container is already mounted, the
   command will fail. This is the default.

.. option:: -s, --save

   Add the containers to ``default-containers`` in configuration file, so
   that they will be mounted at startup.

.. option:: -w, --with-subcontainers

    Mount the subcontainers of those containers. Subcontainers are mounted recursively (i.e. if
    any subcontainers provide own set of subcontainers, mount those too). This is the default.

.. option:: -W, --without-subcontainers

   Do not mount the subcontainers of those containers.

.. option:: -b, --only-subcontainers

   If container contains any subcontainers then mount just the subcontainers and skip mounting
   the container's storage itself.

.. option:: -q, --quiet

   Do not list all the containers to be mounted, useful for a containers with a
   lot of subcontainers.

.. program:: wl-container-mount-watch
.. _wl-container-mount-watch:

:command:`wl container mount-watch <pattern> [<pattern>...]`
------------------------------------------------------------

Mount a list of containers from manifests in Wildland filesystem, then watch
the filesystem for change.

The Wildland system has to be mounted first, see :ref:`wl start <wl-start>`.

Example::

    wl container mount-watch '~/wildland/mynotes/*/*.yaml'

This will attempt to mount, unmount and remount containers as the files matched
by ``/*/*.yaml`` change.

Make sure to use quotation marks, or the wildcard patterns will be expanded
by the shell.


.. program:: wl-container-add-mount-watch
.. _wl-container-add-mount-watch:

:command:`wl container add-mount-watch <pattern> [<pattern>...]`
----------------------------------------------------------------

Modify mount-watch to watch for additional patterns. See
:ref:`wl container mount-watch <wl-container>` for syntax requirements.

Container mount-watch must be running. The Wildland system has to be mounted first,
see :ref:`wl start <wl-start>`.

Example::

    wl container add-mount-watch '~/wildland/mynotes/*/*.yaml'


.. program:: wl-container-stop-mount-watch
.. _wl-container-stop-mount-watch:

:command:`wl container stop-mount-watch`
----------------------------------------

Stop the current mount-watch daemon.


.. program:: wl-container-unmount
.. _wl-container-unmount:

:command:`wl container unmount [--path] [--with-subcontainers/--without-subcontainers] <container>`
---------------------------------------------------------------------------------------------------

.. option:: --path <path>

   Mount path to search for.

.. option:: -w, --with-subcontainers

    Unmount the subcontainers of those containers. Subcontainers are unmounted recursively (i.e. if
    any subcontainer provides own set of subcontainers, unmount those too). This is the default.

.. option:: -W, --without-subcontainers

   Do not unmount the subcontainers of those containers.

.. program:: wl-container-publish
.. _wl-container-publish:

:command:`wl container publish <container> [<wlpath>]`
------------------------------------------------------

Publish a container manifest into user's infrastructure container or under specified wildland path.

.. _wl-container-sign:
.. _wl-container-verify:
.. _wl-container-edit:

:command:`wl container {sign|verify|edit} [...]`
------------------------------------------------------

See :ref:`wl sign <wl-sign>`, :ref:`wl verify <wl-verify>`
and :ref:`wl edit <wl-edit>` documentation.

.. program:: wl-container-sync
.. _wl-container-sync:

:command:`wl container sync <container>`
----------------------------------------

Start synchronizing container's storages.


.. program:: wl-container-stop-sync
.. _wl-container-stop-sync:

:command:`wl container stop-sync <container>`
---------------------------------------------

Stop synchronizing container's storages.


.. program:: wl-container-list-conflicts
.. _wl-container-list-conflicts:

:command:`wl container list-conflicts [--force-scan] <container>`
-----------------------------------------------------------------

List all conflicts detected by container sync.

.. option:: --force-scan

   Force checking all files in all storages and their hashes. Can be slow and bandwidth-intensive.
