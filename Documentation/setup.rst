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

You can also run ``make`` to keep the packages up to date. This tip
applies to both host and docker environments. The Makefile will 
automatically detect whether you're using one of the Docker images
from ``docker/`` directory and execute appropiate commands.


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
    docker-compose build wildland-client-base wildland-client
    docker-compose run --service-ports wildland-client

To create and mount the example containers, run ``wl-example``. wildland-client
is mounted in ``/home/user/wildland`` and the log is in ``/tmp/wlfuse.log``.

The python packages will be reinstalled as a part of an entrypoint. You can still
re-install them manually by running ``make`` without having to terminate the docker 
container.

Running tests:

Tests are automatically executed as part of CI/CD pipelines in an isolated environment
using ``wildland-client-ci`` image. You may also run those tests locally, though to make
this more convenient, you may want to map the project's directory as a volume to override
the code bundled in the image. Use docker-compose's override feature to do that as shown
in the example below:

.. code-block:: sh

    mkdir artifacts # ensure this directory is writable
    cd docker
    docker-compose build wildland-client-base wildland-client-ci
    docker-compose -f docker-compose.yml -f docker-compose.local.yml run wildland-client-ci ./ci/ci-pytest
    docker-compose -f docker-compose.yml -f docker-compose.local.yml run wildland-client-ci ./ci/ci-lint
    # etc...

To come as close as possible to the production environment, you should run tests without
mapping local volumes. Note that this approach would require you to re-build docker image
every time you make changes to the codebase.

.. code-block:: sh

    cd docker
    docker-compose build wildland-client-base wildland-client-ci
    docker-compose run wildland-client-ci ./ci/ci-pytest
    docker-compose run wildland-client-ci ./ci/ci-lint
    # etc...
