.. program:: wl-unpublish
.. _wl-unpublish:

:command:`wl unpublish` - unpublish wildland manifests
======================================================

Synopsis
--------

| :command:`wl unpublish [path]`
| :command:`wl {container|storage|user|bridge} unpublish [path]`

Description
-----------

Unublish a wildland object manifest from the whole of a user's manifests catalog.

If invoked with a manifest type (:command:`wl bridge unpublish`, etc.), it will not require full
path to a manifest but will try to guess manifest location based on it's name.

Options
-------

No options.
