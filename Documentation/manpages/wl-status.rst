.. program:: wl-status
.. _wl-status:

:command:`wl status` --- Display all mounted containers
=======================================================

Synopsis
--------

:command:`wl status [--with-subcontainers/-without-subcontainers]`

Options
-------

.. option:: -w, --with-subcontainers

    List subcontainers.

.. option:: -W, --without-subcontainers

   Do not list subcontainers. This is the default.

.. option:: -p, --with-pseudomanifests

    List containers with pseudo-manifests.

.. option:: -P, --without-pseudomanifests

    Do not list containers with pseudo-manifests. This is the default.

.. option:: -a, --all-paths

    Print all mountpoint paths, including synthetic ones.


:command:`wl status`
