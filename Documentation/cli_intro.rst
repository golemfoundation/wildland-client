Introduction to command-line interface
======================================

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

   $ ./wl user-create User "Wildland Test"
   Using key: 0xfd56724c5a712815390bbda63dba761d9e757f15
   Created: /home/user/.wildland/users/User.yaml
   Using 0xfd56724c5a712815390bbda63dba761d9e757f15 as default user

List users::

   $ ./wl user-list
   0xfd56724c5a712815390bbda63dba761d9e757f15 /home/user/.wildland/users/User.yaml

Create a storage and container manifests::

   $ ./wl storage-create Storage1 --type local --path /tmp/storage
   Using default user: 0xfd56724c5a712815390bbda63dba761d9e757f15
   Created: /home/user/.wildland/storage/Storage1.yaml

   $ ./wl container-create Container --storage Storage1 --path /C1
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
