.. program:: wl-sign
.. _wl-sign:

:command:`wl sign` - sign manifests
===================================

Synopsis
--------

| :command:`wl sign [-i|-o <path>] [<path>]`
| :command:`wl {container|storage|user} sign [-i|-o <path>] [<path>]`

Description
-----------

Sign and encrypt (as needed according to `access` fields) a |~| manifest given by *<path>*,
or stdin if not given. The input file can be a |~| manifest with or without header.
The existing header will be ignored.

If invoked with manifest type (:command:`wl user sign`, etc.), it will also
validate the manifest against schema.

Options
-------

.. option:: -o <path>

   Output to a |~| file. If not given, and also :option:`-i` is not given,
   outputs to standard output

.. option:: -i

   Modify the file in-place.
