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

   $ ./wl user-create "Wildland Test"
   Using key: 0xfd56724c5a712815390bbda63dba761d9e757f15
   Created: /home/user/.wildland/users/wltest.yaml

List users::

   $ ./wl user-list
   0xfd56724c5a712815390bbda63dba761d9e757f15 /home/user/.wildland/users/wltest.yaml

Create and sign a manifest::

   $ cat >storage.yaml
   signer: "0xfd56724c5a712815390bbda63dba761d9e757f15"
   type: local
   path: /tmp/storage
   ^D

   $ ./wl sign -i storage.yaml

Verify the signature::

   $ ./wl verify storage.yaml

Global options
--------------

* ``--base-dir PATH``: base config directory (default is ~/.wildland)
* ``--dummy``: use dummy signatures instead of GPG
* ``--gpg-home PATH``: use different GPG home directory

``wl user-create KEY``
----------------------

Create a new user manifest. You need to have access to corresponding secret
key.

* ``KEY``: GPG key identifier
* ``--name NAME``: name to use for the manifest

``wl user-list``
-----------------

List found user manifests.

``wl sign``
-----------

Sign a manifest file.

* ``wl sign``: read from stdin, write to stdout
* ``wl sign INPUT_FILE``: read from file, write to stdout
* ``wl sign [INPUT_FILE] -o OUTPUT_FILE``: write to a file
* ``wl sign -i FILE``: sign in-place (save to the same file)

``wl verify``
-------------

Verify a manifest signature.

* ``wl verify``: read from stdin
* ``wl verify FILE``: read from file
