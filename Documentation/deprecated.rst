Deprecated features
===================

This page tracks changes that currently go through a deprecation period. That
means the old way of doing things is still (partially) supported, but will be
removed in the future.

The dates are commit dates of introducing the change..

* (2020-08-27) The user manifests should no longer contain public keys in a
  header. Instead, a key is taken either from a bridge manifest, or from a
  local directory (``$HOME/.config/wildland/keys/``).

  Existing manifests with public keys in header are recognized, but display a
  warning, and will not be supported in the future.

* (2020-07-14) The ``wl mount/unmount`` commands have been renamed to
  ``wl start/stop``, and will be removed. The ``wl mount`` command currently
  displays an error message.
