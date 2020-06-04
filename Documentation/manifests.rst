Manifests
=========

A Wildland manifest is a YAML multi-document in a specific format. It consists
of a header, and the manifest body, separated by the standard YAML document
separator (``---``).

Header
------

A YAML manifests begins with a header that contains a ``signature`` field. The
signature is needs to match the ``signer`` field in the manifest body.

Here is an example of a signed manifest:

.. code-block:: yaml

   signature: |
     untrusted comment: signify signature
     RWQIC9hESCJ6WgeQ90xQDJnqcpjcuefWByzLGf/eN5tm+TnaW3DiumWxVliUszTYr5t6Ih8lW3ETCpuEQw5D+s3AhaeH1gIdegw=
   ---
   signer: '0x5a7a224844d80b086445'

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

* there has to be either only a ``signature`` field, or ``signature`` and
  ``pubkey`` fields, in that order
* fields have to be either double quoted (``"foo"``), with exact character
  subset to be determined, or
* multi-line fields have to use a block format with ``|`` as in the example
  above.

The reason for that is because we want to use a simple parser with smaller
attack surface. At the same time, the format should remain compatible with
YAML, i.e. should be parsed by YAML parsers in the same way.

The user manifests are special: they are self-signed, and contain a public key
in the header. For other manifests, the signer is verified against public keys
already loaded from user manifests. See "User manifests" below.

Note that this means we parse the manifest body **before** we know that the
signature matches. However, we already know that it is a correct signature by
a user recognized by the system.

Schema
------

After validating the signature, the YAML body is validated using `JSON Schema
<https://json-schema.org/>`_. The required fields are documented here, but for
the time being, the canonical source of truth are the `schema documents in
wildland-fuse repository
<https://gitlab.com/wild-land/wildland-fuse/-/tree/master/schemas>`_.

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

1. The signer providing the URL (i.e. signer of the manifest the URL is found
   in) must be added to ``local_signers`` in the Wildland configuration file
   (``$HOME/.config/wildland/users``).

   This is to prevent arbitrary signers causing you to access your local
   system.

2. The hostname must be the same as ``local_hostname`` in the Wildland
   configuration file (if the hostname is not provided, it is interpreted as
   ``localhost``).

   This is in order to differentiate between your machines: if you configure
   them with different ``local_hostname``, then file URLs intended for one
   machine will not load on the other.

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

2. The manifest ``signer`` is the same as the storage's ``signer``. Otherwise,
   the manifest will still be parsed (in order to determine the signer) but
   then rejected.


User manifest
-------------

User manifests specify which users are recognized by the system. Currently,
they are loaded from a specific directory (``$HOME/.config/wildland/users``).

All the other manifests have to be verified against known users, i.e. their
``signer`` field has to correspond to the one in user manifest.

The user manifests also contain a ``pubkey`` field in the header, containing
the user's public key. The public key has to
match both the manifest signature and the ``signer`` field.

Example:

.. code-block:: yaml

    signature: |
      ...
    pubkey: |
      ...
    ---
    signer: '0x5a7a224844d80b086445'
    containers:
      - file:///path/to/container.yaml

Fields:

* ``signer`` (fingerprint): Signer of the manifest.
* ``containers`` (list of URLs): Containers associated with that user.

Container manifest
------------------

Example:

.. code-block:: yaml

   signature: ...
   ---
   signer: '0x5a7a224844d80b086445'

   paths:
     - /.uuid/11e69833-0152-4563-92fc-b1540fc54a69
     - /container1
     - /test/a1

   backends:
      storage:
        - file:///path/to/storage11.yaml
        - file:///path/to/storage12.yaml
        - type: local
          path: '/path/to/storage'
          signer: '0x5a7a224844d80b086445'
          container_path: /.uuid/11e69833-0152-4563-92fc-b1540fc54a69

Fields:

* ``signer`` (fingerprint): Signer of the manifest
* ``paths`` (list of absolute paths): Paths in the Wildland namespace where the
  container will be available. The paths are per-signer.

  The first path is recommended to be ``/.uuid/UUID``, but it's a convention,
  not a requirement.

* ``backends``:

  * ``storage`` (list): List of storage manifests. Each can be one of the
    following:

    * a URL pointing to a storage manifest,
    * an inline storage manifest, i.e. a dictionary with all the necessary
      fields.

Storage manifest
----------------

Storage manifests specify storage backends. Different storage backends require
different fields, but ``signer`` and ``type`` fields are always required.

Example:

.. code-block:: yaml

   signature: ...
   ---
   signer: '0x5a7a224844d80b086445'
   type: local
   container_path: /.uuid/11e69833-0152-4563-92fc-b1540fc54a69
   path: /path/to/storage/storage11.yaml

Fields:

* ``signer`` (fingerprint): Signer of the manifest. Needs to match the signer
  of the container.
* ``type``: Type of storage backend. The backend might be unsupported, in which
  case the Wildland driver will skip loading the storage manifest and move on
  to the next one.
* ``container_path``: One of the paths in Wildland namespace for the container
  (by convention, the one with UUID).

  This is in order to prevent attaching a storage to a container it wasn't
  intended for.
* ``read_only`` (optional): This is a read-only storage, editing or deleting
  files is not possible.
* ``trusted`` (optional): This is a trusted storage, manifests inside this
  storage will be accepted without signature, as long as they have the same
  ``signer`` value. See "Unsigned manifests and trusted storage" above.

Local storage (``local``)
~~~~~~~~~~~~~~~~~~~~~~~~~

* ``path``: Absolute path in local filesystem.
