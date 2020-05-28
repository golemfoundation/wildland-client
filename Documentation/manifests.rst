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
     -----BEGIN PGP SIGNATURE-----

     iQEzBAABCAAdFiEEIlVKgqyYrufhjpvjLAOOQqK65gEFAl6PHaEACgkQLAOOQqK6
     5gGQxQf+NFtEM6KWHM6kRBU20xNxc1m0O1xq4G5FabN+1eTcbMtOTZMjQM1pVh7i
     vD7BN2DhYpSiTlJE32W9XQkElTmax79Ahg/bRXj3qGY/IqmS+wdkGdI+hFhsmCC+
     VpJX4FiqcZqWLsFZWaAxX9FbcgxjcTVud0MntOjSHFcblmNBQjLS3x+CwREUAgN+
     5HjTd68u5V40DSiG/u+6h1JmdXP/WkOKECIKzZThAcrQx+16HmScxZFGGCnuNlTn
     Og5phgSSnHR0HrkDso2/4K7KvbvUq3EVxI97fXwSrPviC4HoBsDEAStgAFobEmPI
     65ofO/kXFjaRSp4hRMos64hwY73TwA==
     =Y7sA
     -----END PGP SIGNATURE-----
   ---

   signer: "0x22554a82ac98aee7e18e9be32c038e42a2bae601"

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

Fingerprint format
------------------

The canonical format for fingerprints is ``0x`` followed by a full hexadecimal
fingerprint of the GPG key, in lowercase. Note that **the fingerprint has to be
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

User manifest
-------------

User manifests specify which users are recognized by the system. Currently,
they are loaded from a specific directory (``$HOME/.config/wildland/users``).

All the other manifests have to be verified against known users, i.e. their
``signer`` field has to correspond to the one in user manifest.

The user manifests also contain a ``pubkey`` field in the header, containing
the user's public key (currently, in GPG armor format). The public key has to
match both the manifest signature and the ``signer`` field.

Example:

.. code-block:: yaml

    signature: |
      -----BEGIN PGP SIGNATURE-----
      ...
      -----END PGP SIGNATURE-----
    pubkey: |
      -----BEGIN PGP PUBLIC KEY BLOCK-----
      ...
      -----END PGP PUBLIC KEY BLOCK-----
    ---
    signer: "0x22554a82ac98aee7e18e9be32c038e42a2bae601"
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
   signer: "0x22554a82ac98aee7e18e9be32c038e42a2bae601"

   paths:
     - /.uuid/11e69833-0152-4563-92fc-b1540fc54a69
     - /container1
     - /test/a1

   backends:
      storage:
        - file:///path/to/storage11.yaml
        - file:///path/to/storage12.yaml

Fields:

* ``signer`` (fingerprint): Signer of the manifest
* ``paths`` (list of absolute paths): Paths in the Wildland namespace where the
  container will be available. The paths are per-signer.

  The first path is recommended to be ``/.uuid/UUID``, but it's a convention,
  not a requirement.

* ``backends``:

  * ``storage`` (list of URLs): List of paths to storage manifests, specifying
    storage backends for the container.


Storage manifest
----------------

Storage manifests specify storage backends. Different storage backends require
different fields, but ``signer`` and ``type`` fields are always required.

Example:

.. code-block:: yaml

   signature: ...
   ---

   signer: "0x22554a82ac98aee7e18e9be32c038e42a2bae601"
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

Local storage (``local``)
~~~~~~~~~~~~~~~~~~~~~~~~~

* ``path``: Absolute path in local filesystem.
