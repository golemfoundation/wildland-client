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
     - /container1
     - /test/a1

   backends:
     storage:
       - storage11.yaml
       - storage12.yaml

   # vim: ts=2 sts=2 sw=2 et


Note that we recognize an **extremely limited YAML subset** in the header:

* there has to be only a ``signature`` field
* fields have to be either double quoted (``"foo"``), with exact character
  subset to be determined, or
* multi-line fields have to use a block format with ``|`` as in the example
  above.

The reason for that is because we want to use a simple parser with smaller
attack surface. At the same time, the format should remain compatible with
YAML, i.e. should be parsed by YAML parsers in the same way.

Currently, we delegate the key management to GnuPG. That means that in order to
verify a signature, a key with a given fingerprint has to be found in the GnuPG
keyring. In addition, the signer is verified against a list of known users (see
"User manifests").

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

User manifest
-------------

User manifests specify which users are recognized by the system. Currently,
they are loaded from a specific directory (``$HOME/.wildland/users``).

All the other manifests have to be verified against known users, i.e. their
``signer`` field has to correspond to the one in user manifest.

Example:

.. code-block:: yaml

   signature: ...
   ---
   pubkey: "0x22554a82ac98aee7e18e9be32c038e42a2bae601"
   signer: "0x22554a82ac98aee7e18e9be32c038e42a2bae601"

Fields:

* ``signer`` (fingerprint): Signer of the manifest.
* ``pubkey`` (fingerprint): User's public key, currently has to be the same as
  ``signer``.

Container manifest
------------------

Example:

.. code-block:: yaml

   signature: ...
   ---
   signer: "0x22554a82ac98aee7e18e9be32c038e42a2bae601"

   paths:
     - /container1
     - /test/a1

   backends:
      storage:
        - /path/to/storage11.yaml
        - /path/to/storage12.yaml

Fields:

* ``signer`` (fingerprint): Signer of the manifest
* ``paths`` (list of absolute paths): Paths in the Wildland namespace where the
  container will be available. The paths are per-signer.
* ``backends``:

  * ``storage`` (list of URLs): List of paths to storage manifests, specifying
    storage backends for the container. (TODO URL format)


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
   path: /path/to//storage/storage11

Fields:

* ``signer`` (fingerprint): Signer of the manifest.
* ``type``: Type of storage backend. The backend might be unsupported, in which
  case the Wildland driver will skip loading the storage manifest and move on
  to the next one.

Local storage (``local``)
~~~~~~~~~~~~~~~~~~~~~~~~~

* ``path``: Absolute path in local filesystem. Currently, relative paths are
  supported, but this is temporary.
