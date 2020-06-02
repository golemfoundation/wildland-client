Command-line interface
======================

The command-line interface is used for user and manifest management. It's in a
very early stage, so things might change quickly.

The entry point is ``wildland-cli``, with ``wl`` shortcut for provided for
convenience.


Quick start
-----------

Create a user::

   $ ./wl user create User
   Generated key: 0x5a7a224844d80b086445
   No path specified, using: /users/User
   Created: /home/user/.config/wildland/users/User.yaml
   Using 0x5a7a224844d80b086445 as default user
   Adding 0x5a7a224844d80b086445 to local signers

List users::

   $ ./wl user list
   /home/user/.config/wildland/users/User.yaml
     signer: 0x5a7a224844d80b086445
     path: /users/User

Create a container and storage manifests. You need to first create a container,
and then attach storage to it::

   $ ./wl container create Container --path /C1
   Created: /home/user/.config/wildland/containers/Container.yaml

   $ ./wl storage create local Storage1 --path /tmp/storage --container Container
   Using container: /home/user/.config/wildland/containers/Container.yaml (/.uuid/589e53d9-54ae-4036-95d7-4af261e7746f)
   Created: /home/user/.config/wildland/storage/Storage1.yaml
   Adding storage to container
   Saving: /home/user/.config/wildland/containers/Container.yaml

Mount it all::

   $ ./wl mount
   Mounting: /home/user/wildland

   $ ./wl container mount Container
   Mounting: /home/user/.config/wildland/containers/Container.yaml

   $ ls -a ~/wildland
   .  ..  .control  .users  .uuid  C1

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
* ``key_dir``: path for key pairs, default ``~/.config/wildland/keys``
* ``mount_dir``: path to mount Wildland in, default ``~/wildland``
* ``dummy``: if true, use dummy signatures instead of Signify
* ``default_user`` (as key fingerprint): default user for newly created manifests

Keys and signatures
-------------------

Public key cryptography is handled by `Signify
<https://github.com/aperezdc/signify>`_, OpenBSD's tool for signing and
verification.

After generating, the keys are stored in ``key_dir`` (by default,
``~/.config/wildland/keys``). The public-private key pair is stured in
``<fingerprint>.pub`` and ``<fingerprint>.sec`` files.

Manual pages
------------

.. toctree::
   :maxdepth: 3
   :glob:

   manpages/*
