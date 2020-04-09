Setup and tests
===============

System requirements
-------------------

We're working on Debian and Fedora.

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
