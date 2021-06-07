Deprecated features
===================

This page tracks changes that currently go through a deprecation period. That
means the old way of doing things is still (partially) supported, but will be
removed in the future.

The dates are commit dates of introducing the change..

* (2021-06-04) Dropped support for relative paths to user manifests in bridges.

* (2021-05-31) The ``infrastructures`` field in user manifest has been renamed to
  ``manifests-catalog``. For backwards compatibility, both fields are
  permitted when loading a manifest, but only the latter one is used. Also completely
  removed support for the older, obsolete form of 'containers'.

* (2021-04-28) Storage sets are now deprecated. Instead, storage templates now accept multiple
  templates as an array of yaml objects. Manual adjustment of existing templates is required as
  they **must** be an array of objects.

* (2021-04-15) Renamed ``http-index`` storage backend to ``http``.

* (2021-02-08) Rename --user to --owner in ``wl container create``.

* (2021-02-04) JSON Schemas should be referenced with '/schemas/' prefix now,
  for example ``{ "$ref": "/schemas/types.json#url"}``.

* (2020-02-08) Signify encryption backend is no longer supported. Unfortunately manifests
  have to be re-signed.

* (2020-01-08) Renamed --user to --owner when creating a bridge to not confuse
  user to whom the bridge is pointing vs user who is signing (hence owning)
  the bridge manifest.

* (2020-12-16) 'inner-container' for field of proxy storage backends renamed
  to 'reference-container'.

* (2020-09-30) Config entries 'local-signers' and '@default-signer' are
  renamed to 'local-owners' and '@default-owner'. Old values are still loaded,
  but a warning is logged.

* (2020-09-30) Old 'signer' field in manifests is now renamed to 'owner'. Old
  manifests will be correctly loaded, but new manifests will have an 'owner'
  field.

* (2020-09-10) Local manifests are now created with appropriate suffix:
  ``<name>.container.yaml``, ``<name>.bridge.yaml`` etc.

  However, commands that take a "short name" still recognize the old manifests
  without the suffix. For example, ``wl container mount C`` will look for both
  ``$HOME/.config/wildland/containers/C.yaml`` and
  ``$HOME/.config/wildland/containers/C.container.yaml``.

  After this change is removed, the "short name" will always resolve to a file
  name with suffix.

  Note that the above doesn't apply to full file paths.

* (2020-08-27) The user manifests should no longer contain public keys in a
  header. Instead, a key is taken either from a bridge manifest, or from a
  local directory (``$HOME/.config/wildland/keys/``).

  Existing manifests with public keys in header are recognized, but display a
  warning, and will not be supported in the future.
