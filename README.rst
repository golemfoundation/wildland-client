|Coverage|

.. |Coverage| image:: https://gitlab.com/wildland/wildland-client/badges/master/coverage.svg?job=pytest
   :target: https://wildland.gitlab.io/wildland-client/coverage/

Wildland Client
===============

Wildland is a collection of protocols, conventions, software, and (soon) a marketplace for leasing storage and -- in the future -- compute infrastructure. All these pieces work together with one goal in mind: to decouple the user's data from the underlying infrastructure.

This repository contains Wildland Client software - the part used to access data stored with Wildland and serve them as a (FUSE based) filesystem. It also allows to manage Wildland Containers.

More information can be found in the `documentation <https://docs.wildland.io>`_

The primary location of the source code is at `gitlab.com <https://gitlab.com/wildland/wildland-client>`. Please use this location for contributing (reporing issues, contributing code etc).


Quick start
-----------

Currently the primary method of running wildland-client, is to use bundled docker image:

.. code-block:: sh

   cd docker
   docker-compose build
   docker-compose run --service-ports wildland-client

Alternatively, run directly:

.. code-block:: sh

   ./wildland-docker.sh

This container serves FUSE content as WebDAV too.

See `Setup <https://wildland.gitlab.io/wildland-client/setup.html>`_ for more.


Repository structure
--------------------

* ``Documentation/``: project documentation, in ReST/Sphinx format
* ``ci/``: Docker setup for CI
* ``docker/``: Docker setup for local testing
* ``wl``, ``wildland-cli``: command-line interface entry point
* ``wildland-fuse``: FUSE driver entry point
* ``wildland/``: Python source code

  * ``wildland/schemas/``: Manifest schemas in `JSON Schema <https://json-schema.org/>`_
    format
  * ``wildland/tests/``: Tests (in Pytest framework)
* ``plugins/``: storage backends (as separate Python packages)

License
-------

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

See `COPYING` file for the full license text.

In order to be able to contribute to any Wildland repository, you will need to
agree to the terms of the `Wildland Contributor Agreement
<https://docs.wildland.io/contributor-agreement.html>`_. By contributing to any
such repository, you agree that your contributions will be licensed under the
GPLv3 License.
