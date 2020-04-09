wildland in FUSE
================

`Documentation <https://wild-land.gitlab.io/wildland-fuse/>`_

Quick start
-----------

.. code-block:: sh

   cd docker
   docker-compose build
   docker-compose run wildland-fuse

See `Setup <https://wild-land.gitlab.io/wildland-fuse/setup.html>`_ for more.


Repository structure
--------------------

* ``Documentation/``: project documentation, in ReST/Sphinx format
* ``docker/``: Docker setup, for local testing and CI
* ``example/``: Example manifests, keys, etc., used in Docker setup
* ``schemas/``: Manifest schemas in `JSON Schema <https://json-schema.org/>`_
  format
* ``wl``, ``wildland-cli``: command-line interface entry point
* ``wildland-fuse``: FUSE driver entry point
* ``wildland/``: Python source code

  * ``wildland/tests/``: Tests (in Pytest framework)
