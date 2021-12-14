# Wildland Redis backend

Implementation of Redis backend for Wildland.

This backend is optimised to be used as a storage for Wildland catalogue (ie. Wildland manifest
files). It should not be used to store large files as the data is stored in Redis DB.

The keys in selected Redis database reflect the filesystem tree. Each key is prefixed with `prefix`
paramter in the storage schema definition.

## TLS

The backend currently does not support [TLS](https://gitlab.com/wildland/wildland-client/-/issues/727) connections.
