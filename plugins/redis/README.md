# Wildland Redis backend

Implementation of Redis backend for Wildland.

This backend is optimised to be used as a storage for Wildland catalogue (ie. Wildland manifest
files). It should not be used to store large files as the data is stored in Redis DB.

The keys in selected Redis database reflect the filesystem tree. Each key is prefixed with `prefix`
parameter in the storage schema definition.

## Redis ACL

Recommended Redis ACL groups for this backend implemenation are:

* `-@all`
* `+@write`
* `+@read`
* `+@connection`
* `+@transaction`
* `+select`
