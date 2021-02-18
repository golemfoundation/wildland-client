.. _wl-manifests:

Manifests
=========

A Wildland manifest is a YAML multi-document in a specific format. It consists
of a header, and the manifest body, separated by the standard YAML document
separator (``---``).

Header
------

A YAML manifests begins with a header that contains a ``signature`` field. The
signature is needs to match the ``owner`` field in the manifest body.

Here is an example of a signed manifest:

.. code-block:: yaml

   signature: RWQIC9hESCJ6WgeQ90xQDJnqcpjcuefWByzLGf/eN5tm+TnaW3DiumWxVliUszTYr5t6Ih8lW3ETCpuEQw5D+s3AhaeH1gIdegw=
   ---
   owner: '0x5a7a224844d80b086445'

   paths:
     - /.uuid/11e69833-0152-4563-92fc-b1540fc54a69
     - /container1
     - /test/a1

   backends:
     storage:
       - file:///path/to/storage11.yaml
       - file:///path/to/storage12.yaml

   # vim: ts=2 sts=2 sw=2 et

We also support the old signature format, with a comment:

.. code-block:: yaml

   signature: |
     untrusted comment: signify signature
     RWQIC9hESCJ6WgeQ90xQDJnqcpjcuefWByzLGf/eN5tm+TnaW3DiumWxVliUszTYr5t6Ih8lW3ETCpuEQw5D+s3AhaeH1gIdegw=

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
<https://gitlab.com/wild-land/wildland-client/-/tree/master/wildland/schemas>`_.

Keys and signatures
-------------------

Public key cryptography is handled by `Signify
<https://github.com/aperezdc/signify>`_, OpenBSD's tool for signing and
verification. The keys and signatures use Signify's format: a single-line
untrusted comment, then Base64-encoded data.

The canonical format for fingerprints is ``0x`` followed by a 20 hexadecimal
digits; the first 10 bytes of the key. Note that **the fingerprint has to be
quoted**, otherwise it will be interpreted as a YAML number and fail
validation.

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
(``$HOME/.config/wildland/keys``). Otherwise, the key is loaded from a trust
manifest.

Example:

.. code-block:: yaml

    signature: ...
    ---
    owner: '0x5a7a224844d80b086445'
    infrastructures:
      - file:///path/to/container.yaml
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
   owner: '0x5a7a224844d80b086445'

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
        - type: local
          path: '/path/to/storage'
          owner: '0x5a7a224844d80b086445'
          container-path: /.uuid/11e69833-0152-4563-92fc-b1540fc54a69

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
   owner: '0x5a7a224844d80b086445'
   type: local
   container-path: /.uuid/11e69833-0152-4563-92fc-b1540fc54a69
   path: /path/to/storage/

Fields:

.. schema:: storage.schema.json

For more information on ``trusted`` field, see See "Unsigned manifests and
trusted storage" above.

The ``manifest-pattern`` field specifies how to determine manifest paths for
path traversal. Currently, one type of pattern is supported::

    manifest-pattern:
      type: glob
      path: /manifests/{path}/*.yaml

The ``path`` is an absolute path that can contain ``*`` and ``{path}``.
``{path}`` is expanded to the container path we are looking for.

Bridge manifest
---------------

Bridge manifests introduce a new user. A bridge manifest is usually stored in a
container, and has to be signed by the container's owner. For more
information, see :doc:`Wildland paths </paths>`.

Example:

.. code-block:: yaml

   signature: ...
   ---
   owner: '0x5a7a224844d80b086445'
   user: ./User.yaml
   pubkey: RWTHLJ4ZI+VFTMJKqvCT0j4399vEVrahx+tpO/lKfVoSsaCTTGQuX78M
   paths:
   - /users/User

Fields:

.. schema:: bridge.schema.json
