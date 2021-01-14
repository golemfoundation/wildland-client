Deprecated features
===================

This page tracks changes that currently go through a deprecation period. That
means the old way of doing things is still (partially) supported, but will be
removed in the future.

The dates are commit dates of introducing the change..

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

* (2020-09-01) The ``containers`` field in user manifest has been renamed to
  ``infrastructures``. For backwards compatibility, both fields are
  permitted when loading a manifest, but only the latter one is used.

* (2020-08-27) The user manifests should no longer contain public keys in a
  header. Instead, a key is taken either from a bridge manifest, or from a
  local directory (``$HOME/.config/wildland/keys/``).

  Existing manifests with public keys in header are recognized, but display a
  warning, and will not be supported in the future.

* (2020-07-14) The ``wl mount/unmount`` commands have been renamed to
  ``wl start/stop``, and will be removed. The ``wl mount`` command currently
  displays an error message.
