.. program:: wl-verify
.. _wl-verify:

:command:`wl verify` - verify manifests
=======================================

Synopsis
--------

| :command:`wl verify [path]`
| :command:`wl {container|storage|user} sign [path]`

Description
-----------

Verify a |~| manifest given by *path*, or stdin if not given. The input file can
be a |~| manifest with or without header. The existing header will be ignored.

If invoked with manifest type (:command:`wl user verify`, etc.), it will also
validate the manifest against schema.

Options
-------

No options.
