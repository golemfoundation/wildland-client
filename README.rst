wildland in FUSE
================

Requirements
------------

.. code-block:: sh

   apt install \
      python3-fuse \
      python3-voluptuous \
      python3-yaml \

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
