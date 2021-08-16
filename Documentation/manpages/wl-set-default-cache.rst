.. program:: wl-set-default-cache
.. _wl-set-default-cache:

:command:`wl set-default-cache` --- Set default template for container cache storages
=====================================================================================

Synopsis
--------

:command:`wl set-default-cache TEMPLATE`

Description
-----------

Storage template given by TEMPLATE will be set as default for newly created container cache
storages when using :command:`wl container mount --with-cache`.
See :ref:`wl container create-cache <wl-container-create-cache>` for details about caches.
