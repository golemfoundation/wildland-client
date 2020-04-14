Command-line interface
======================

The command-line interface is used for user and manifest management. It's in a
very early stage, so things might change quickly.

The entry point is ``wildland-cli``, with ``wl`` shortcut for provided for
convenience.

Quick start
-----------

Generate a GPG key::

   $ gpg2 --gen-key
   Real name: Wildland Test
   Email address:

Create a user::

   $ ./wl user-create "Wildland Test" --name User
   Using key: 0xfd56724c5a712815390bbda63dba761d9e757f15
   Created: /home/user/.wildland/users/User.yaml
   Using 0xfd56724c5a712815390bbda63dba761d9e757f15 as default user

List users::

   $ ./wl user-list
   0xfd56724c5a712815390bbda63dba761d9e757f15 /home/user/.wildland/users/User.yaml

Create a storage and container manifests::

   $ ./wl storage-create --name Storage1 --type local --path /tmp/storage
   Using default user: 0xfd56724c5a712815390bbda63dba761d9e757f15
   Created: /home/user/.wildland/storage/Storage1.yaml

   $ ./wl container-create --name Containter --storage Storage1 --path /C1
   Using default user: 0xfd56724c5a712815390bbda63dba761d9e757f15
   Using storage: /home/user/.wildland/storage/Storage1.yaml
   Created: /home/user/.wildland/containers/Containter.yaml

Mount it all::

   $ ./wl mount
   Mounting: /home/user/wildland

   $ ./wl container-mount C1
   Mounting: /home/user/.wildland/containers/C1.yaml

   $ ls -a ~/wildland
   .  ..  .control  c2

Global options
--------------

* ``--base-dir PATH``: base config directory (default is ~/.wildland)
* ``--dummy``: use dummy signatures instead of GPG
* ``--gpg-home PATH``: use different GPG home directory

Configuration file
------------------

The file ``~/.wildland/config.yaml`` specifies all the defaults. Here are the
supported fields:

* ``user_dir``: path for user manifests, default ``~/.wildland/users``
* ``storage_dir``: path for storage manifests, default ``~/.wildland/storage``
* ``container_dir``: path for container manifests, default ``~/.wildland/containers``
* ``mount_dir``: path to mount Wildland in, default ``~/wildland``
* ``dummy``: if true, use dummy signatures instead of GPG
* ``gpg_home``: path to GPG home directory
* ``default_user`` (as key fingerprint): default user for newly created manifests

Manifest commands
-----------------

The following commands work on all the manifests:

* ``wl sign`` - sign a manifest file

  * ``wl sign``: read from stdin, write to stdout
  * ``wl sign INPUT_FILE``: read from file, write to stdout
  * ``wl sign [INPUT_FILE] -o OUTPUT_FILE``: write to a file
  * ``wl sign -i FILE``: sign in-place (save to the same file)

* ``wl verify`` - verify a signature

  * ``wl verify``: read from stdin
  * ``wl verify FILE``: read from file

* ``wl edit FILE`` - edit a file, then check and sign it (``visudo``-style)

  * ``--editor`` - use a specific editor command instead of ``$EDITOR``

In addition, these commands work on specific types of manifests:

* ``wl user-{sign,verify,edit}``
* ``wl storage-{sign,verify,edit}``
* ``wl container-{sign,verify,edit}``

When the type of manifest is known, you can refer to a manifest just by a short
name (e.g. ``wl container-sign C1`` will know to look for
``~/.wildland/users/C1.yaml``). The manifests will also be verified against
schema.

Users
-----

* ``wl user-create KEY`` - create a new user

  * ``KEY`` is GPG key identifier
  * ``--name NAME``: name to use for the manifest

* ``wl user-list``: list known users

Storage
-------

* ``wl storage-create`` - create a new user

  * ``--user USER``: user name to use for signing
  * ``--name NAME``: name to use for the manifest
  * ``--type``: storage type (only ``local`` is supported for now)
  * ``--path PATH``: path for local storage

* ``wl storage-list``: list known storages

Containers
----------

* ``wl container-create`` - create a new container

  * ``--user USER``: user name to use for signing
  * ``--name NAME``: name to use for the manifest
  * ``--path PATH``: mount path for container (can be repeated)
  * ``--storage STORAGE``: storage to use for container (can be repeated)

* ``wl container-list``: list known containers

* ``wl container-mount CONTAINER``: mount a container

* ``wl container-unmount CONTAINER``: unmount a container

  * ``wl container-unmount --path PATH``: unmount a container mounted under a
    specific path

    
Mounting
--------

* ``wl mount``: mount the Wildland filesystem (see ``mount_dir`` in
  Configuration file)

* ``wl unmount``: unmount the Wildland filesystem
