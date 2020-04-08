wildland in FUSE
================

Requirements
------------

Debian:

.. code-block:: sh

   apt install \
      gnupg2 \
      python3-fuse \
      python3-jsonschema \
      python3-yaml \
      python3-pytest \
      python3-gnupg
   
Fedora:

.. code-block:: sh

   dnf install \
      gnupg2 \
      python3-jsonschema \
      python3-yaml \
      python3-pytest \
      fuse-devel \
      python3-devel \
      python3-gnupg

   git clone git@github.com:libfuse/python-fuse.git                
   pip3 install --user python-fuse

Make sure to use a ``python-fuse`` 1.0.0 or newer, the old version has
`compatibility issues with Python 3
<https://github.com/libfuse/python-fuse/issues/13>`_.

Mount
-----

.. code-block:: sh

   mkdir mnt
   ./wildland-fuse ./mnt -f \
      -o log=-,manifest=./example/manifests/container1.yaml,manifest=./example/manifests/container2.yaml

Options:

* ``-f`` will make the driver run in foreground (you can't Ctrl-C it, though, you
  have to unmount)
* ``log=-`` will log to stderr (you can also log to a file)
* ``manifest=...`` (can be repeated) will mount a container with given manifest
  (this is optional, you can also add containers afterwards using the
  ``.control`` system)

Unmount
-------

.. code-block:: sh

   fusermount -u ./mnt

Run tests
---------

.. code-block:: sh

   pytest -v

Tips & Tricks:

* ``pytest -s``: don't capture output.
* ``pytest -k test_name``
* Use ``breakpoint()`` in code to drop into debugger (you might need to run
  ``pytest -s``)

  * WARNING: Use with care. This will cause a FUSE process to pause, which
    means that any application trying to read from the user directory will hang
    in uninterruptible sleep.

Docker
------

There is also docker image to conveniently test it in non-Debian environment.
Because of FUSE usage, it still may require Linux environment though.

Usage:

.. code-block:: sh

   cd docker
   docker-compose build
   docker-compose run wildland-fuse

wildland-fuse is mounted in ``/mnt`` and the log is in ``/tmp/wlfuse.log``

Running tests:

.. code-block:: sh

   cd docker
   docker-compose build
   docker-compose run wildland-fuse test.sh -v

Control interface
-----------------

There is a procfs-like interface under ``.control/``:

* ``.control/paths`` - list of paths and corresponding containers, by number::

      /container1 0
      /container2 1
      /path/for/container1 0

* ``.control/containers/<NUM>`` - container directories:

  * ``manifest.yaml``
  * ``/storage/<NUM>/manifest.yaml``

* ``.control/cmd`` - commands (write-only file):

  * ``mount MANIFEST_FILE``
  * ``unmount MANIFEST_FILE``

* ``.control/mount`` - mount a manifest provided directly (``cat manifest.yaml >
  .control/mount``); note: absolute paths are required

Signed manifests
----------------

The manifests have to be signed. The driver does not yet verify real
signatures, but this will come soon.  (For now, the signature is of the form
``"dummy.<signer>"``).

A manifest has to begin with a **header**, which is a simple YAML document with
two fields: ``signer`` and ``signature``. Here is an example of a signed
manifest:

.. code-block:: yaml

   signer: "user"
   signature: "dummy.user"
   ---

   signer: user

   # the rest of the manifest follows

Here is another example, using GPG signatures (not supported yet):

.. code-block:: yaml

   signer: "0xb6ddcc11f5818361b4ab7fc96ecfa72aa270e421"
   signature: |
     -----BEGIN PGP SIGNATURE-----

     iLMEAAEIAB0WIQTN5mjRHoGC6gDA3uxiDPaaIicROgUCXoyB/gAKCRBiDPaaIicR
     Os58A/4oWmZXGJzecUdgZ1kCw7bKO+tyz5kMRBslFhbwyBE8XA4zZUYm9x5enhvT
     6tA3PFFr7S/3w978evGchie6KBip9UjhxAq69iGVa+JEz2Wc8wHYW7sJGsBxO+tY
     IAJM5o5o2OuEaDMqS3fFmOVUJvuWEjmMjQ6dCF9vuE5E+BjWAA==
     =OO/K
     -----END PGP SIGNATURE-----
   ---

   signer: 0xb6ddcc11f5818361b4ab7fc96ecfa72aa270e421

   # the rest of the manifest follows


Note that we recognize an **extremely limited YAML subset** in the header:

* there have to be only ``signer`` and ``signature`` fields, in that order
* fields have to be either double quoted (``"foo"``), with exact character
  subset to be determined, or
* multi-line fields have to use a block format with ``|`` as in the example
  above.

The reason for that is because we want to use a simple parser with smaller
attack surface. At the same time, the format should remain compatible with
YAML, i.e. should be parsed by YAML parsers in the same way.
