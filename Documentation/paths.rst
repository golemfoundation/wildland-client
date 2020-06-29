Wildland paths
==============

A Wildland path identifies a container, or a file in a container. Many commands
that operate on containers, such as ``wl container mount``, accept Wildland
paths.

It has the following form::

    0xabcd:/path/one:/path/two:/path/to/file.txt

* The first part (before ``:``) is the signer. It can be omitted, in which case
  the ``default-user`` (from configuration) will be used.

* The next parts are container paths. The first container has to be known
  locally (i.e. available in ``~/.config/wildland/containers``), the next ones
  have their manifests found in the previous container (see "Path resolution"
  below).

* The last part is the file path inside container. It can be omitted, in which
  case the path refers to a container, not to a file inside.

Path resolution
---------------

When there is more than one container path (the part between colons), the path
resolution algorithm needs to traverse from one container to the next.

Suppose that our path is ``:/path/one:/path/two:``, and we have found the
container (and associated storage) for ``/path/one``.

* First, we determine the ``manifest-pattern`` for the storage (see "Manifests"
  for details). The ``manifest-pattern`` describes how to look for container
  manifests.

  The default pattern uses the container path directly, meaning we would look
  for ``/path/two.yaml`` file in the container. However, if the pattern is more
  complex, for instance ``/manifests/*.yaml``, we would list all files in the
  ``/manifests/`` directory.

* We determine the files based on ``manifest-pattern``, and examine them.

  If there is a container manifest with the right path (in this case,
  ``/path/two``), we use that container. The signer has to be the same as for
  the outer container.

  If there is a user manifest, we load containers for that user and look for a
  container with the right path (in this case, ``/path/two``).

  If there are multiple containers, we check them all.

Normally, the manifest signature is verified, unless the storage is marked as
``trusted``, in which case we accept unsigned manifests.
