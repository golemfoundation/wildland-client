.. program:: wl-container
.. _wl-container:

********************************************
:command:`wl container` - Container commands
********************************************

Synopsis
========

| :command:`wl {container|containers} list`
| :command:`wl container info NAME`
| :command:`wl container delete [--force] [--cascade] NAME`
| :command:`wl container create [--owner <user>] --path <path> [--path <path2> ...] [--storage-template <storage_template>]`
| :command:`wl container create-cache --template <template_name> <container>`
| :command:`wl container delete-cache <container>`
| :command:`wl container update [--storage <storage>] <container>`
| :command:`wl container mount []`
| :command:`wl container unmount`
| :command:`wl container modify [] <file>`
| :command:`wl container publish <container>`
| :command:`wl container unpublish <container>`

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

:command:`wl {container|containers} list`
-----------------------------------------

List known containers.

.. program:: wl-container-info
.. _wl-container-info:

:command:`wl container info NAME`
---------------------------------------------------------

Display a short summary of a single container. The information is equivalent to
:command:`wl container list`, but for one container only.

.. program:: wl-container-delete
.. _wl-container-delete:

:command:`wl container delete [--force] [--cascade] [--no-unpublish] NAME`
--------------------------------------------------------------------------

Delete a container from local filesystem and unpublish it, if published.

.. option:: --force, -f

   Delete even if the container refers to local storage manifests.

.. option:: --cascade

   Delete together with all local storage manifests.

.. option:: --no-unpublish, -n

    Do not attempt to unpublish the container before deleting it.

.. program:: wl-container-create
.. _wl-container-create:

:command:`wl container create [--owner <user>] [--path <path>] [--path <path2> ...] [--storage-template <storage-template>] [--encrypt-manifest/--no-encrypt-manifest] [--access <user>] [--no-publish]`
--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

Create a |~| new container manifest.

.. option:: --path <path>

   The paths under which the container will be mounted.

.. option:: --owner <user>, --user <user>

   The owner of the container. The ``--user`` alias is deprecated.

   .. todo:: Write the config name for default user.

.. option:: --title <title>

    Title of the container. Used when generating paths based on categories.

.. option:: --category </path/to/category>

    Category to use in generating paths. Requires --title. May be provided multiple times.

.. option:: -u, --update-user

   Add the container to the user manifest.

.. option:: -n, --no-update-user

   Don't add the container to the user manifest. This is the default.

.. option:: --storage-template <storage_template>, --template

   Create storages for a container with a given storage-template.

.. option:: --local-dir <local_dir>

    Local directory to be passed to storage templates as a parameter. Requires --storage-template.

.. option:: --encrypt-manifest

    Encrypt container manifest so that it's readable only by the owner. This is the default.

.. option:: --no-encrypt-manifest

    Do not encrypt container manifest at all.

.. option:: --access USER

    Allow an additional user access to this container manifest. This requires --encrypt-manifest
    (which is true by default).

.. option:: --no-publish

   Do not publish the container after creation. By default, if the container owner has proper
   infrastructure defined in the user manifest, the container is published.


.. program:: wl-container-create-cache
.. _wl-container-create-cache:

:command:`wl container create-cache --template <template_name> <container> [<container>...]`
--------------------------------------------------------------------------------------------

Create a cache storage for container(s) from a template. This is used to speed up accessing
slow remote storages like s3. The template should usually be the default local storage one
(`wl template create local --location /path/to/cache/root template_name`).

On the first container mount, old primary storage's content (usually a slow remote one) is copied
to the cache storage. From then on the cache storage becomes container's primary storage
when the container is mounted. Old primary storage is kept in sync with the cache when mounted.

Cache storage is created based on the template provided. Because the purpose of the cache storage
is to be fast, it's best to use a local storage template unless some specific setup is needed.
When using a default local storage template as outlined above, the cache storage directory
is `/path/to/cache/root/container_uuid`.

Cache manifests are stored in `<Wildland config root>/cache` directory and are storage manifests.
Wildland storage commands can be used to display or manually edit them. They have file names
in the form of `owner_id.container_uuid.storage.yaml`.


.. option:: -t, --template <template_name>

   Name of the storage template to use.


.. program:: wl-container-delete-cache
.. _wl-container-delete-cache:

:command:`wl container delete-cache <container> [<container>...]`
-----------------------------------------------------------------

Deletes cache storage associated with container(s).


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

:command:`wl container mount [--verbose/-v] [--remount/--no-remount] [options] <container> [<container>...]`
------------------------------------------------------------------------------------------------------------

Mount a container given by name or path to manifest. The Wildland system has to
be started first, see :ref:`wl start <wl-start>`.
Wildland paths are supported too, including unambiguous (with wildcards or else) ones.
For example: ``wildland:@default:/path/to/user:*:``

The container(s) will be mounted under paths declared in the container
manifest, nested into a owner-specific directory. If the container owner is the
default user (see :ref:`wl start <wl-start>`), then the container will be
mounted directly under the FUSE root directory. Otherwise, it will be mounted
under paths defined by bridges between users. In addition, containers are
always mounted nested under `/.users/<user-id>:`, also when the container is
owned by the default user.
Directories that transition to another user (like - bridges) are marked with
colon (``:``) at the end, thus the path in the filesystem looks very similar to WL
path. To avoid confusion, any other colon within container or bridge path is
replaced with underscore (``_``).

For example:

- default owner is set to UserA (user id `0xaaa...`)
- there is a bridge owned by UserA pointing at UserB (user id `0xbbb...`) under path `/people/UserB`
- there is a bridge owned by UserB pointing at UserC (user id `0xccc...`) under path `/people/UserC`
- user mounts a container of UserC with paths `/docs/projectX` and `/timeline/2021-01-02`

The mounted container will be available under the following paths:
- `/.users/0xccc...:/docs/projectX` and `/.users/0xccc...:/timeline/2021-01-02`
- `/people/UserB:/people/UserC:/docs/projectX` and `/people/UserB:/people/UserC:/timeline/2021-01-02`

The second point is built from bridges from UserA to UserC.

In some cases, there might be multiple possible bridges or multiple containers in users' manifests
catalogs. In both circumstances all paths will be considered, but cycles will be avoided.

.. option:: -r, --remount

   Replace the container currently mounted, if any. The container is identified
   by its first path.

.. option:: -n, --no-remount

   Don't replace existing container. If the container is already mounted, the
   command will fail. This is the default.

.. option:: -s, --save

   Add the containers to ``default-containers`` in configuration file, so
   that they will be mounted at startup.

.. option:: --import-users

   Import user manifests encountered when loading the containers to mount. This
   is applicable when contianer is given as a WL path. When enabled, further
   mounts of the same user container can reference the user directly, instead of
   through a directory (specifically - a bridge manifest in it).
   Enabled by default.

.. option:: --no-import-users

   Do not import user manifests when mounting a container through a WL path.

.. option:: -w, --with-subcontainers

    Mount the subcontainers of those containers. Subcontainers are mounted recursively (i.e. if
    any subcontainers provide own set of subcontainers, mount those too). This is the default.

.. option:: -W, --without-subcontainers

   Do not mount the subcontainers of those containers.

.. option:: -b, --only-subcontainers

   If container contains any subcontainers then mount just the subcontainers and skip mounting
   the container's storage itself.

.. option:: -c, --with-cache

   Create and use a cache storage for the container using the default cache template
   (see :ref:`wl set-default-cache <wl-set-default-cache>`).
   See :ref:`wl container create-cache <wl-container-create-cache>` for details about caches.

.. option:: --cache-template <template_name>

   Create and use a cache storage for the container from the given template.
   See :ref:`wl container create-cache <wl-container-create-cache>`.

.. option:: -l, --list-all

   During mount, list all the containers to be mounted and result of mount (changed/not changed).
   Can be very long in case of Wildland paths or numerous subcontainers.

.. option:: -m, --manifests-catalog

   Allow to mount manifests catalog containers.

   Currently if a user wants to mount the whole forest (i.e. all the containers), the supported syntax is this:

      wl c mount `:/forests/User:*:`

   But we also support mounting of the manifests catalog containers, i.e. those that hold the manifests for the
   forest, using the following syntax:

      wl c mount :/forests/User:

   This latter syntax is very similar to the above syntax and it is very easy for users to confuse the two.

   In order to better differentiate between these two actions, the second syntax can be made more explicit using
   the `--manifests-catalog` option:

      wl c mount --manifests-catalog :/forests/User:

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

The pattern can be also a container WL path, either specific (like
``wildland::/users/alice:/docs/notes:``), or wildcard (like
``wildland::/users/alice:*:``).

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

:command:`wl container unmount [--path] [--with-subcontainers/--without-subcontainers] [--undo-save] <container>`
-----------------------------------------------------------------------------------------------------------------

.. option:: --path <path>

   Mount path to search for.

.. option:: -w, --with-subcontainers

   Unmount the subcontainers of those containers. Subcontainers are unmounted recursively (i.e. if
   any subcontainer provides own set of subcontainers, unmount those too). This is the default.

.. option:: -W, --without-subcontainers

   Do not unmount the subcontainers of those containers.

.. option:: -u, --undo-save

   Undo ``wl container mount --save <container>``. ``<container>`` must be specified exactly the
   same as when running ``wl container mount --save <container>``.

   For example, if you run::

      wl c mount --save '~/mnt/.manifests/.uuid/*'

   then it will not work::

      wl c unmount --undo-save '~/mnt/.manifests/.uuid/*.yaml'

   Also make sure to quote ``~/mnt/.manifests/.uuid/*.yaml`` unless you want it to be expanded by
   your shell instead of Wildland itself.

.. program:: wl-container-publish
.. _wl-container-publish:

:command:`wl container publish <container>`
-------------------------------------------

Publish a container manifest into user's manifests catalog (first container from the catalog
that provides read-write storage will be used).

.. program:: wl-container-unpublish
.. _wl-container-unpublish:

:command:`wl container unpublish <container>`
---------------------------------------------

Unublish a container manifest from the whole of a user's manifests catalog.

.. _wl-container-sign:
.. _wl-container-verify:

:command:`wl container {sign|verify} [...]`
-------------------------------------------

See :ref:`wl sign <wl-sign>` and :ref:`wl verify <wl-verify>` documentation.


.. program:: wl-container-edit
.. _wl-container-edit:

:command:`wl container edit PATH`
---------------------------------

Edit, sign and republish a container. The command will launch an editor and
validate the edited file before signing and republishing it.

If an absolute path, container name or file:// URL is passed, the container will be considered
a local file.

.. option:: --editor <editor>

   Use custom editor instead of the one configured with usual :envvar:`VISUAL`
   or :envvar:`EDITOR` variables.

.. option:: -r, --remount

   If editing a container, attempt to remount it afterwards. This is the
   default

.. option:: -n, --no-remount

   If editing a container, do not attempt to remount it afterwards.

.. option:: --publish, -p

   By default, if the container is already published, the modified version
   of the container manifest will be republished.

.. option:: --no-publish, -P

   Do not attempt to republish the container after modification.


.. program:: wl-container-dump
.. _wl-container-dump:

:command:`wl container dump PATH`
---------------------------------

The command will output manifest contents (without signature and by default decrypted)
in a machine-readable way.

If an absolute path, container name or file:// URL is passed, the container will be considered
a local file.

.. option:: -d, --decrypt

   Decrypt any encrypted fields, if possible. This is the default.

.. option:: -n, --no-decrypt

   Do not decrypt any encrypted fields.


.. program:: wl-container-sync
.. _wl-container-sync:

:command:`wl container sync [--target-storage <id_or_type>] [--source-storage <id_or_type>] [--one-shot] [--no-wait] <container>`
---------------------------------------------------------------------------------------------------------------------------------

Start synchronizing two of a container's storages, by default the first local storage with the
first non-local storage in the manifest).

.. option:: --source-storage <id_or_type>

   Specify which should be the source storage for syncing; can be specified as a backend-id
   or as storage type (e.g. 's3'). If not --one-shot, source and target storages are symmetric.

.. option:: --target-storage <id_or_type>

   Specify which should be the target storage for syncing; can be specified as a backend-id
   or as storage type (e.g. 's3'). The choice will be saved in config and used as default in future container
   syncs. If not --one-shot, source and target storages are symmetric.

.. option:: --one-shot

    Perform one-time sync, do not maintain sync.

.. option:: --no-wait

    Do not wait for a one-time sync to finish, run in the background. Requires --one-shot.

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

.. program:: wl-container-duplicate
.. _wl-container-duplicate:

:command:`wl container duplicate [--new-name <new-name>] <container>`
---------------------------------------------------------------------

Duplicate a given container as a container called <new-name>, optionally adding it to the
user manifest. UUIDs and backend-ids are updated, everything else remains the same.

.. option:: --new-name <new-name>

   Name for the newly created container.

.. program:: wl-container-modify
.. _wl-container-modify:

:command:`wl container modify [--add-path <path> ...] [--del-path <path> ...] [--add-access <user> ...] [--del-access <user> ...] [--add-category <path> ...] [--del-category <path> ...] [--del-storage <storage>] [--title] [--encrypt-manifest] [--no-encrypt-manifest] [--publish/--no-publish] [--remount/--no-remount] <file>`
------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

Modify a container |~| manifest given by *<file>*.

.. option:: --add-path

   Path to add. Can be repeated.

.. option:: --del-path

   Path to remove. Can be repeated.

.. option:: --add-access

   User to add access for. Can be repeated.

.. option:: --del-access

   User to revoke access from. Can be repeated.

.. option:: --add-category

   Category to add. Can be repeated.

.. option:: --del-category

   Category to remove. Can be repeated.

.. option:: --del-storage

   Storages to remove. Can be either the backend_id of a storage or position in
   storage list (starting from 0). Can be repeated.

.. option:: --title

   Title to set.

.. option:: --encrypt-manifest

    Encrypt manifest given by *<file>* so that it's only readable by its owner.

.. option:: --no-encrypt-manifest

    Stop encrypting manifest given by *<file>*.

.. option:: --publish, -p

   By default, if the container is already published, the modified version
   of the container manifest will be republished.

.. option:: --no-publish, -P

   Do not attempt to republish the container after modification.

.. option:: --remount, -r

   By default, if the container is already mounted, the modified version
   of the container will be remounted.

.. option:: --no-remount, -n

   Do not attempt to remounting the container after modification.

.. _wl-container-find:

:command:`wl container find <file>`
-----------------------------------

Show which container exposes the mounted file.
