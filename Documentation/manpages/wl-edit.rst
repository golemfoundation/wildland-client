.. program:: wl-edit
.. _wl-edit:

:command:`wl edit` - Edit and sign a manifest in a |~| safe way.
================================================================

Synopsis
--------

| wl edit [OPTIONS] FILE

Description
-----------

The command will launch an editor and validate the edited file before signing
and replacing it.

If invoked with manifests type (:command:`wl user edit`, etc.), the command
will also validate the manifest against schema.

Options
--------

.. option:: --editor <editor>

   Use custom editor instead of the one configured with usual :envvar:`VISUAL`
   or :envvar:`EDITOR` variables.
