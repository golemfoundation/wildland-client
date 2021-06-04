.. program:: wl-version
.. _wl-version:

:command:`wl version` --- Display Wildland version
==================================================

Synopsis
--------

:command:`wl version`

Description
-----------

Display Wildland version. On `git` repository, it reads value from annotated version tag and expects a format `vX.Y.Z`
where `X`, `Y` and `Z` are digits. When no version tag is found, it uses abbreviated commit hash (default length is 7).

The fallback value is given by using hardcoded `__version__` in `wildland.__init__`.
