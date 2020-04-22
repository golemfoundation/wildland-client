Manifest commands
=================

The following commands work on all the manifests.

In addition, there are versions that will work on specific types of manifests:

* ``wl user {sign,verify,edit}``
* ``wl storage {sign,verify,edit}``
* ``wl container {sign,verify,edit}``

When the type of manifest is known, you can refer to a manifest just by a short
name (e.g. ``wl container-sign C1`` will know to look for
``~/.config/wildland/containers/C1.yaml``). The manifests will also be verified against
schema.

``wl sign``
-----------

.. argparse::
   :module: wildland.cli
   :func: make_parser
   :prog: wl
   :path: sign

``wl verify``
-------------

.. argparse::
   :module: wildland.cli
   :func: make_parser
   :prog: wl
   :path: verify


``wl edit``
-------------

.. argparse::
   :module: wildland.cli
   :func: make_parser
   :prog: wl
   :path: edit
