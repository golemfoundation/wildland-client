Wildland paths
==============

A Wildland path identifies a container, or a file in a container. Many commands
that operate on containers, such as ``wl container mount``, accept Wildland
paths.

It has the following form::

    wildland:0xabcd@https{wildland.url/manifest.yaml}:/path/one:/path/two:/path/to/file.txt

* The ``wildland:`` prefix denotes that it's a Wildland path

* The second part (before ``:``) is the owner. It can be omitted, in which case
  the ``@default`` (from configuration) will be used.

  The ``@default`` and ``@default-owner`` values are also supported, and
  resolved according to configuration.

  The owner can be followed by hint: ``@https{address.of.manifest}``, which specifies the location
  of the user manifest (the ``address.of.manifest`` is accessed using https
  protocol, other protocols might be supported in the future).
  Using the hint requires explicitly specified owner (not a @default or
  @default-owner, and not omitted).

* The next parts are container or user (bridge) paths. This part may be set as
  a ``*`` wildcard. See "Path resolution" below.

* The last part is the file path inside container. It can be omitted, in which
  case the path refers to a container, not to a file inside.

* A ``user access path`` refers to a Wildland path pointing at a user bridge. For example,
  ``0xintermediate_user@https{wildland.url/path/to/forest-owner.user.yaml}:/users/destination_user:``.
  The original URL ``https://wildland.url/path/to/forest-owner.user.yaml`` returns
  the catalog manifest for ``0xintermediate_user`` that knows user ``destination_user``.

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
  for ``/path/two.container.yaml`` file in the container. However, if the pattern is more
  complex, for instance ``/manifests/*.{object-type}.yaml``, we would list all files in the
  ``/manifests/`` directory.

* We determine the files based on ``manifest-pattern``, and examine them.

  If there is a container manifest with the right path (in this case,
  ``/path/two``), we use that container. The owner has to be the same as for
  the outer container.

  If there is a bridge manifest, we check if that manifest contains the right
  path (in this case, ``/path/two``).

  If so, we load the user manifest indicated by that bridge manifest, and
  load containers for that user.

Normally, the manifest signature is verified, unless the storage is marked as
``trusted``, in which case we accept unsigned manifests.

Furthermore, a path can be set as ``*`` wildcard. Currently a ``*`` on its own
is supported, not full patterns (``:/path/one:*:`` is ok,
``:/path/one:/path/*:`` is not).

Local manifests
---------------

In addition, we recognize some locally stored manifests, depending on the
current owner:

* We bootstrap the search process by looking at local **container manifests**,
  and locally stored **user manifest** for the given owner.

* When resolving the next parts, we again consider the local **container
  manifests**, as well as locally stored **bridge manifests**.

Note that the manifests need to be stored under the right path
(``$HOME/config/wildland/``), and the owner must be recognized: there needs to
exist a user manifest, as well as a public key (under
``$HOME/config/wildland/keys/KEY.pub``).
