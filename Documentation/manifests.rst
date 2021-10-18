.. _wl-manifests:

Manifests
=========

A Wildland manifest is a YAML multi-document in a specific format. It consists
of a header, and the manifest body, separated by the standard YAML document
separator (``---``). Contrary to the YAML format, duplicate keys and anchors
usage are not allowed.

Header
------

A YAML manifests begins with a header that contains a ``signature`` field. The
signature is needs to match the ``owner`` field in the manifest body.

Here is an example of a signed manifest:

.. code-block:: yaml

   signature: 0x1b567f3ed1404fd81da06e34e4487ff01a1be2d72b07a065e8f6b84008aff6d5:kJq+h9yXCILDmflwfy4rFYA17r42TzIAnp3y6khYlqqHlrYcD0KxIAOwFr1wXHjUAA2h4HEYQwzf6l4SRXEyDA==
   ---
   owner: '0x1b567f3ed1404fd81da06e34e4487ff01a1be2d72b07a065e8f6b84008aff6d5'

   paths:
     - /.uuid/11e69833-0152-4563-92fc-b1540fc54a69
     - /container1
     - /test/a1

   backends:
     storage:
       - file:///path/to/storage11.yaml
       - file:///path/to/storage12.yaml

   # vim: ts=2 sts=2 sw=2 et

Note that we recognize an **extremely limited YAML subset** in the header:

* currently, the only header field is ``signature``
* fields have to be either double quoted (``"foo"``), with exact character
  subset to be determined, or
* multi-line fields have to use a block format with ``|`` as in the example
  above.

The reason for that is because we want to use a simple parser with smaller
attack surface. At the same time, the format should remain compatible with
YAML, i.e. should be parsed by YAML parsers in the same way.

The user manifests are special: they are self-signed, and contain a public key
in the header. For other manifests, the owner is verified against public keys
already loaded from user manifests. See "User manifests" below.

Note that this means we parse the manifest body **before** we know that the
signature matches. However, we already know that it is a correct signature by
a user recognized by the system.

Schema
------

After validating the signature, the YAML body is validated using `JSON Schema
<https://json-schema.org/>`_. The required fields are documented here, but for
the time being, the canonical source of truth are the `schema documents in
wildland-client repository
<https://gitlab.com/wildland/wildland-client/-/tree/master/wildland/schemas>`_.

Keys and signatures
-------------------

Public key cryptography is handled by libsodium (see https://libsodium.gitbook.io/doc/).
Keys are in the Ed25519 format, signatures consist of a key fingerprint (sha256 hash of public key)
and base64 signature, separated by a ':'.

The canonical format for fingerprints is ``0x`` followed by a sha256 hash of the public key,
encoded in hex. Note that **the fingerprint has to be quoted**, otherwise it will be interpreted as
a YAML number and fail validation.

Keys are stored in key_dir (as per config file, by default it's (``$HOME/.config/wildland/keys``),
in files <key_id>.pub (for public key) and <key_id>.sec (for private key).

The public key file format is: key prefix (`Ed`) concatenated with 32 bytes of public signing key
and 32 bytes of public encryption key, all encoded in base64.

The private key file format is: key prefix (`Ed`) concatenated with 32 bytes of public signing key,
32 bytes of public encryption key, 32 bytes of private signing key and 32 bytes of private
encryption key, all encoded in base64.


Encryption
----------

Container and storage manifests can be encrypted. By default, such manifests are encrypted to the
key of their owner (and thus only readable by the owner). Access for additional users can be
provided via 'access' fields, for example:

.. code-block:: yaml

   owner: '0x1b567f3ed1404fd81da06e34e4487ff01a1be2d72b07a065e8f6b84008aff6d5'
   paths:
     - /.uuid/11e69833-0152-4563-92fc-b1540fc54a69
     - /container1
   access:
     - user: '0x8c83f2a9b6fd91ee189e3d38eff661a7335322c9a81700ebfc99725235c098e2'
   backends:
     storage:
       - file:///path/to/storage11.yaml

This manifest will be encrypted to both its owner and any additional users specified in the 'access'
field. To get an unencrypted manifest, a special value of ``user: '*'`` can be used:

.. code-block:: yaml

   owner: '0x1b567f3ed1404fd81da06e34e4487ff01a1be2d72b07a065e8f6b84008aff6d5'
   paths:
     - /.uuid/11e69833-0152-4563-92fc-b1540fc54a69
     - /container1
   access:
     - user: '*'
   backends:
     storage:
       - file:///path/to/storage11.yaml

Access field can also be used in an inline storage manifest. If provided, the inline manifest will
be encrypted only to the users specified in the inline access field - which can be a smaller user
set than for the entire manifest. This is useful especially for manifests with any sort of
vulnerable data, such as access keys, inside.

.. code-block:: yaml

   owner: '0x1b567f3ed1404fd81da06e34e4487ff01a1be2d72b07a065e8f6b84008aff6d5'
   paths:
     - /.uuid/11e69833-0152-4563-92fc-b1540fc54a69
     - /container1
   access:
     - user: '*'
   backends:
     storage:
        - type: local
          path: '/path/to/storage'
          owner: '0x1b567f3ed1404fd81da06e34e4487ff01a1be2d72b07a065e8f6b84008aff6d5'
          container-path: /.uuid/11e69833-0152-4563-92fc-b1540fc54a69
          access:
             - user: '0x1b567f3ed1404fd81da06e34e4487ff01a1be2d72b07a065e8f6b84008aff6d5'

Encrypted manifests are stored like normal manifests, as a signed yaml files.
An encrypted manifest contains a single 'encrypted' field, with two properties: 'encrypted-data'
and 'encrypted-keys'.

.. code-block:: yaml

    encrypted:
      encrypted-data: uGiAkrAH2J3Ze0zExxkxsEw5MgesvckD17J8mhEovzrK15jII1Vr3/GtbFfOdpPRDd9YFIdnRQAuGJndP4HSxeIO4WRqhEXlYcSg+MRl5xBrVGOyGEgcABir2fNbuIx/OosEky4EQVRAt2VWJ8BXxgagWj8JlYJNeC70AZTCBgIvXD4ZJ5ERwPtqh5XpIE6Re2/uN9Vx8O7MqgPXErLd5ysdj80S/uX/VVpc5qK7QTxXFNPoONzh3g8UIJeyuK1ssrXuBM7Zi8Uzc7Th1TcZqnnEMdDolySiYO61mRwwHC/mutsJ9jY1H//K3vydE++exr4cfEMNWxC/FR2exCgrNGSRXRF+v2uEOTFPWBgEOxkVCw==
      encrypted-keys:
         - 9kZzha84yghdN7/P7Y7SCvRLDapcVHp4XSMuHVBmdz0eI/BEyLvOw1sOafrfaYc/miQMc7bkxtYH6AOWwzVbeuFbP7JudPDiByTEWniJfUQ=

If the whole manifest is not encrypted, but a storage manifest inside is encrypted, same format is
used for the inline manifest:

.. code-block:: yaml

    object: container
    owner: '0x8c83f2a9b6fd91ee189e3d38eff661a7335322c9a81700ebfc99725235c098e2'
    paths:
       - /.uuid/a2b04017-c87f-48d7-9844-f230104c50db
       - /container1
    access:
       - user: '*'
    backends:
       storage:
        - encrypted:
           encrypted-data: 84xb9yzus+DUAAGO1k9PuJjgMxfdHdbU/rKPDzC20Xo/w0uObSDDaQu/8NBGE6Bp+YP4wFftghaXRFIocm78e0hMfkVFRJQED8TPArdfw7KYO+vHjOVoAPBNn4+wTYGtuY4xSE94BoJ/wuoG7Vwg+zPUmsWtL063W4AYaxJckh9ZCxRsSyPyrM8bhF7OrT/h2lbzXNttX4FYFUa8hD1uSHNAu4AUCEhEToLHaWJ8tXd/pE8tlNJDaR40m6Shg00Q4JRlPSVGfsA9rFrtTRS3lsaxmgWS3KZ3yHAOXWBsWBnZsy2HKZza7m2gQb21Vv+nA/oXRTCFUgpeMQdb97Y=
           encrypted-keys:
              - 0/72AyRsv1zeZlq/spiH6kdXEeVLZgK+rbszXj4sPEb3ZPrgiSQFYi7PESNUR19ksDQumzrYkDehBzj6mMgG5/os3Z3Wh3JG5JTl+nT7JYA=
              - FAlt1INt+phM9/I5d0wRKNALFA/+BRDzR6mYQD2dQ3EPavfHd+NFKs7UxaTs1y4WBYW26aPKykHDpHCKKAYji1cvE9UxxqA4X+AjAMiCa6E=

Manifests are (if possible, that is, if appropriate keys are available) encrypted and decrypted
transparently. ``wl edit`` allows the user to edit decrypted manifest, while ``wl dump`` allows
to quickly see decrypted manifest contents. ``wl sign`` encrypts and signs any manifests provided
to it.


Local URLs
----------

In places where a URL is expected, you can use a local file URL. These are of
the form ``file://<hostname>/<path>``, where the hostname is optional.

For a local URL to be recognized, two conditions must be met:

1. The owner providing the URL (i.e. owner of the manifest the URL is found
   in) must be added to ``local_owners`` in the Wildland configuration file
   (``$HOME/.config/wildland/users``). Alternatively, a directory (or any of
   its parents) where the referenced file lives needs to have a
   ``.wildland-owners`` file that includes the URL owner id.

   This is to prevent arbitrary signers causing you to access your local
   system.

2. The hostname must be the same as ``local_hostname`` in the Wildland
   configuration file (if the hostname is not provided, it is interpreted as
   ``localhost``).

   This is in order to differentiate between your machines: if you configure
   them with different ``local_hostname``, then file URLs intended for one
   machine will not load on the other.

The rules in the first point apply also to storage backends accessing local
files (``local``, ``local-cached``, etc).

Unsigned manifests and trusted storage
--------------------------------------

In certain circumstances, manifests without signature are also accepted by
Wildland. Such manifests have to contain a header separator, but the header can
be empty (i.e. a manifest will begin with ``---``).

A manifest without signature is be accepted as long as the following
requirements are met:

1. The manifest originates from a storage marked as trusted (i.e. with
   ``trusted`` enabled in the storage manifest).

   In case of local files, this is determined by checking that a file path
   resolves to a currently-mounted storage.

2. The manifest ``owner`` is the same as the storage's ``owner``. Otherwise,
   the manifest will still be parsed (in order to determine the owner) but
   then rejected.


User manifest
-------------

User manifests specify which users are recognized by the system. Currently,
they are loaded from a specific directory (``$HOME/.config/wildland/users``).

All the other manifests have to be verified against known users, i.e. their
``owner`` field has to correspond to the one in user manifest.

In order to be loaded, the system has to know a public key for a user. For
local manifests, that means a corresponding key is in the keys directory
(``$HOME/.config/wildland/keys``). Otherwise, the key is loaded from a bridge
manifest.

User manifest serves important role in describing user's forest:

1. It specifies what keys can be used for signing this user's manifests (the
   ``pubkeys`` field).
2. It specifies where to look for this user's manifests, in the
   ``manifests-catalog`` field. See the next section for details.

Example:

.. code-block:: yaml

    signature: ...
    ---
    owner: '0x1b567f3ed1404fd81da06e34e4487ff01a1be2d72b07a065e8f6b84008aff6d5'
    manifests-catalog:
      - file:///path/to/container.yaml
      - object: link
        storage:
          type: local
          location: '/path/to/storage'
          owner: '0x1b567f3ed1404fd81da06e34e4487ff01a1be2d72b07a065e8f6b84008aff123'
          backend-id: '3cba7968-da34-4b8c-8dc7-83d8860a8933'
        file: '/container.yaml'
    pubkeys:
      - RWTHLJ4ZI+VFTMJKqvCT0j4399vEVrahx+tpO/lKfVoSsaCTTGQuX78M
      - ...

Fields:

.. schema:: user.schema.json


Container manifest
------------------

Example:

.. code-block:: yaml

   signature: ...
   ---
   owner: '0x1b567f3ed1404fd81da06e34e4487ff01a1be2d72b07a065e8f6b84008aff6d5'

   paths:
     - /.uuid/11e69833-0152-4563-92fc-b1540fc54a69
     - /container1
     - /test/a1

   title: Example Container

   categories:
     - /important/examples
     - /documentation/examples/containers

   backends:
      storage:
        - file:///path/to/storage11.yaml
        - file:///path/to/storage12.yaml
        - location: /home/user/my_local_container_storage
          backend-id: 54e62924-3c65-4bbb-a82c-2b89a05af99b
          object: storage
          type: local
        - location: /home/user/my_dropbox_container_storage
          app-key: fbct8l3dt8aq25m
          refresh-token: t9XizOh056UBAAAAAAAAAU2Rvmq1eMRwZAXOmfln8CURovLkhjY5nht-PnAp38FI
          backend-id: 674817fa-3b91-4c6e-afb5-7ab4b9e23109
          object: storage
          type: dropbox

In every category directory, every other category will be mounted. Please note that for a given container,
each ``backend-id`` attribute of storages is unique.

Fields:

.. schema:: container.schema.json

Storage manifest
----------------

Storage manifests specify storage backends. Different storage backends require
different fields, but ``owner`` and ``type`` fields are always required.

Example:

.. code-block:: yaml

   signature: ...
   ---
   owner: '0x1b567f3ed1404fd81da06e34e4487ff01a1be2d72b07a065e8f6b84008aff6d5'
   type: local
   container-path: /.uuid/11e69833-0152-4563-92fc-b1540fc54a69
   path: /path/to/storage/

Fields:

.. schema:: storage.schema.json

For more information on ``trusted`` field, see See "Unsigned manifests and
trusted storage" above.


Bridge manifest
---------------

Bridge manifests introduce a new user. A bridge manifest is usually stored in a
container, and has to be signed by the container's owner. For more
information, see :doc:`Wildland paths </paths>`.

Example:

.. code-block:: yaml

   signature: ...
   ---
   owner: '0x1b567f3ed1404fd81da06e34e4487ff01a1be2d72b07a065e8f6b84008aff6d5'
   user: ./User.yaml
   pubkey: RWTHLJ4ZI+VFTMJKqvCT0j4399vEVrahx+tpO/lKfVoSsaCTTGQuX78M
   paths:
   - /users/User

Fields:

.. schema:: bridge.schema.json

Bridge manifest itself can be mounted too, similar to a container. When
mounted, it containes a single file ``WILDLAND-FOREST.txt`` with a short info.
This mainly serves as a placeholder for the actual forest - to clearly see what
forests are reachable via exising bridges.

Technically, mounting a bridge is implemented as a container deterministically
generated from a Bridge manifest. This container has:

 - ``owner`` - same as the _target_ user
 - ``paths`` - ``/`` (to appear at the root level of the forest), and
   ``/.uuid/...`` with a deterministically generated UUID, based on a target user ID
 - ``backends`` - a single storage backend of type ``static``, with just
   ``WILDLAND-FOREST.txt`` file

Links
-----

In places in which you want to refer to a certain manifest (currently, in user's manifests catalog
and bridges), you can also use a 'link' object. A link contains an inline storage manifest (in
'storage' field) and an absolute path to the manifest file contained within in the 'file' field.


Manifests catalog
-----------------

Manifests catalog is a selected container in user's forest, designated to store
that user's manifests. Which container(s) serve this role, is selected in the
User manfest. There can be several manifests catalogs in the User manifest - in
this case, all of them are consulted when looking for a container(s) (the
search does not stop on the first match). Note this is different from a single
manifest catalog with several storage backends - when a container has several
storage backends, they are expected to represent the same content, and so only
the first (accessible) storage (of each manifests catalog) is checked.

Manifests catalog specify how other manifests are stored within. The mechanism
can be different for each storage backend, but in most cases manifests are
stored as separate files, under file names specified with a
``manifest-pattern`` field (in the Storage manifest). Typical Container
manifest serving as a Manifests catalog may look like this:

.. code-block:: yaml

   object: container
   version: '1'
   owner: '0x1b567f3ed1404fd81da06e34e4487ff01a1be2d72b07a065e8f6b84008aff6d5'
   paths:
   - /.uuid/d1cd4f43-7c4b-498f-bf1b-2eb92b2daa49
   - /.manifests
   backends:
     storage:
     - type: http
       manifest-pattern:
         path: /{path}.yaml
         type: glob
       read-only: true
       url: https://example.com/my-manifests-catalog
     - type: webdav
       manifest-pattern:
         path: /{path}.yaml
         type: glob
       url: https://example.com/dav/my-manifests-catalog
       credentials:
         login: login
         password: password

Note the ``manifest-pattern`` field - in this case, it specifies that manifests
are stored in a path built from a container path(s), with appended ``.yaml``
suffix. See `_Subcontainers </subcontainers>` for more details.

The above container has two storage backends defined - the first one (with
``type: http``) is read-only, the second one is read-write (it doesn't have
``read-only: true`` flag). This means, the first one (if accessible) will be
used for container lookups (because it is the first one listed). But when
saving a manifest into the catalog, WL will use the second (writable) storage
backend. This setup is especially useful if the read-only access is faster than
read-write access.
