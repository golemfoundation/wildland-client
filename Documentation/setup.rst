Setup and tests
===============

System requirements
-------------------

We're working on Debian and Fedora.

Debian:

.. code-block:: sh

   apt install \
      python3-dev \
      python3-venv \
      fuse \
      libfuse-dev

(See also ``ci/Dockerfile``).

Fedora:

.. code-block:: sh

   dnf install \
      fuse-devel \
      python3-devel \
      libbsd-devel


Install Python packages
-----------------------

.. code-block:: sh

   python3 -m venv env/
   . ./env/bin/activate
   pip install -r requirements.dev.txt
   pip install -e . plugins/*

(You can also run ``make`` to keep the packages up to date).

Or, the quick-and-dirty way, without virtualenv::

   pip3 install --user -r requirements.dev.txt
   pip3 install --user -e . plugins/*


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
    docker-compose run wildland-client

To create and mount the example containers, run ``wl-example``. wildland-client
is mounted in ``/home/user/wildland`` and the log is in ``/tmp/wlfuse.log``.

Running tests:

.. code-block:: sh

    cd ci
    docker-compose build
    docker-compose run wildland-client-ci ./ci/ci-pytest

(or ``./ci/ci-lint``, ``./ci/ci-docs``)
