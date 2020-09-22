wildland in FUSE
================

|Coverage|

.. |Coverage| image:: https://gitlab.com/wild-land/wildland-client/badges/master/coverage.svg?job=pytest
   :target: https://wild-land.gitlab.io/wildland-client/coverage/

`Documentation <https://wild-land.gitlab.io/wildland-client/>`_

Quick start
-----------

.. code-block:: sh

   cd docker
   docker-compose build
   docker-compose run --service-ports wildland-fuse

This container serves FUSE content as WebDAV too.

See `Setup <https://wild-land.gitlab.io/wildland-client/setup.html>`_ for more.


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
