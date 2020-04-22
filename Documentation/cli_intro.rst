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

   $ ./wl user create User --key "Wildland Test"
   Using key: 0xfd56724c5a712815390bbda63dba761d9e757f15
   Created: /home/user/.config/wildland/users/User.yaml
   Using 0xfd56724c5a712815390bbda63dba761d9e757f15 as default user

List users::

   $ ./wl user list
   0xfd56724c5a712815390bbda63dba761d9e757f15 /home/user/.config/wildland/users/User.yaml

Create a container and storage manifests. You need to first create a container,
and then attach storage to it::

   $ ./wl container create Container --path /C1
   Using default user: 0xfd56724c5a712815390bbda63dba761d9e757f15
   Created: /home/user/.config/wildland/containers/Containter.yaml

   $ ./wl storage create Storage1 --type local --path /tmp/storage \
          --container Container --update-container
   Using default user: 0xfd56724c5a712815390bbda63dba761d9e757f15
   Using container: /home/user/.config/wildland/containers/Container.yaml (/.uuid/9434c95b-9860-46cc-90dd-d32d6f410aa3)
   Created: /home/user/.config/wildland/storage/Storage1.yaml
   Adding storage to container
   Saving: /home/user/.config/wildland/containers/Container.yaml

Mount it all::

   $ ./wl mount
   Mounting: /home/user/wildland

   $ ./wl container mount C1
   Mounting: /home/user/.config/wildland/containers/C1.yaml

   $ ls -a ~/wildland
   .  ..  .control  c2

Global options
--------------

* ``--base-dir PATH``: base config directory (default is ``~/.config/wildland``)

Configuration file
------------------

The file ``~/.config/wildland/config.yaml`` specifies all the defaults. Here are the
supported fields:

* ``user_dir``: path for user manifests, default ``~/.config/wildland/users``
* ``storage_dir``: path for storage manifests, default ``~/.config/wildland/storage``
* ``container_dir``: path for container manifests, default ``~/.config/wildland/containers``
* ``mount_dir``: path to mount Wildland in, default ``~/wildland``
* ``dummy``: if true, use dummy signatures instead of GPG
* ``gpg_home``: path to GPG home directory
* ``default_user`` (as key fingerprint): default user for newly created manifests
