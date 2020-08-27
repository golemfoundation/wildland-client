.. program:: wl-trust
.. _wl-trust:

************************************
:command:`wl trust` - Trust commands
************************************

Synopsis
========

| :command:`wl trust create`
| :command:`wl trust edit`
| :command:`wl trust sign`
| :command:`wl trust verify`

Description
===========

These are commands to manage trust manifests.

Commands
========

.. program:: wl-trust-create
.. _wl-trust-create:

:command:`wl trust create [--user USER] --ref-user USER --ref-user-location URL-OR-PATH [--ref-user-path PATH] FILE_PATH`
-------------------------------------------------------------------------------------------------------------------------

Create a new trust manifest under ``FILE_PATH``.

.. option:: --user USER

   User for signing.

.. option:: --ref-user USER

   User to refer to.

.. option:: --ref-user-location URL-OR-PATH

   Path to use for user manifest. This is either an URL, or a relative part
   (starting with ``./`` or ``../``).

.. option:: --ref-user-path PATH

   Path for the user in Wildland namespace. Repeat for multiple paths.

   The paths override the paths in user manifest. If not provided, the paths
   will be copied from user manifest.


.. _wl-trust-sign:
.. _wl-trust-verify:
.. _wl-trust-edit:

:command:`wl trust {sign|verify|edit} [...]`
------------------------------------------------------

See :ref:`wl sign <wl-sign>`, :ref:`wl verify <wl-verify>`
and :ref:`wl edit <wl-edit>` documentation.
