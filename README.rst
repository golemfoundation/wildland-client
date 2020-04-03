wildland in FUSE
================

Requirements
------------

Debian:

.. code-block:: sh

   apt install \
      python3-fuse \
      python3-voluptuous \
      python3-yaml \
      python3-pytest
   
Fedora:

.. code-block:: sh

   dnf install \
      python3-voluptuous \
      python3-yaml \
      python3-pytest \
      fuse-devel \
      python3-devel

   git clone git@github.com:libfuse/python-fuse.git                
   pip3 install --user python-fuse

Make sure to use a `python-fuse` 1.0.0 or newer, the old version has
`compatibility issues with Python 3
<https://github.com/libfuse/python-fuse/issues/13>`_.

Mount
-----

.. code-block:: sh

   mkdir mnt
   /sbin/mount.fuse ./wildland-fuse ./mnt \
      -o manifest=./example/manifests/container1.yaml,manifest=./example/manifests/container2.yaml
   tail -F /tmp/wlfuse.log

Unmount
-------

.. code-block:: sh

   fusermount -u ./mnt

Run tests
---------

.. code-block:: sh

   pytest -v

Tips & Tricks:

* `pytest -s`: don't capture output.
* `pytest -k test_name`
* Use `breakpoint()` in code to drop into debugger (you might need to run
  `pytest -s`)

Docker
------

There is also docker image to conveniently test it in non-Debian environment.
Because of FUSE usage, it still may require Linux environment though.

Usage:

.. code-block:: sh

   cd docker
   docker-compose build
   docker-compose run wildland-fuse

wildland-fuse is mounted in `/mnt` and the log is in `/tmp/wlfuse.log`

Running tests:

.. code-block:: sh

   cd docker
   docker-compose build
   docker-compose run wildland-fuse test.sh -v

Control interface
-----------------

There is a procfs-like interface under `.control/`:

* `.control/paths` - list of paths and corresponding containers, by UUID:

  ..code-block::

      /container1 UUID1
      /container2 UUID2
      /path/for/container1 UUID1

* `.control/containers/<UUID>` - container directories:
    * `/storage/0/manifest.yaml`

* `.control/cmd` - commands (write-only file):
   * `mount MANIFEST_FILE`
   * `unmount MANIFEST_FILE`

* `.control/mount` - mount a manifest provided directly (`cat manifest.yaml >
  .control/mount`); note: absolute paths are required
