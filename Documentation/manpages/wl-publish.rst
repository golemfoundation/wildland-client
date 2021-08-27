.. program:: wl-publish
.. _wl-publish:

:command:`wl publish` - publish wildland manifests
==================================================

Synopsis
--------

| :command:`wl publish [path]`
| :command:`wl {container|storage|user|bridge} publish [path]`

Description
-----------

Publish a wildland object manifest into user's manifests catalog (first container from the catalog
that provides read-write storage will be used).

If invoked with a manifest type (:command:`wl bridge publish`, etc.), it will not require full path
to a manifest but will try to guess manifest location based on it's name.

Options
-------

No options.
