.. program:: wl-start
.. _wl-start:

:command:`wl start` --- Start the Wildland FUSE driver
================================================================

Synopsis
--------

:command:`wl start [--debug] [--remount] [--container <container>] [--single-thread]`

Options
-------

.. option:: --remount, -r

   If mounted already, remount. Default is to fail.

.. option:: --debug, -d

   Debug mode: run in foreground. Repeat for more verbosity.

.. option:: --container <container>, -c <container>

   Container to mount after starting. Can be repeated.

.. option:: --single-thread, -S

   Run single-threaded.

.. option:: --skip-default-containers, -s

   Don't mount ``default-containers`` from configuration file. The default is
   to mount them.

.. option:: --default-user

   Specify a default user different than specified in configuration file. This will be used
   until Wildland FUSE driver is stopped.

.. option:: --skip-forest-mount

   Don't mount forest containers of default user.
