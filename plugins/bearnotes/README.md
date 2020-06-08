# Wildland backend for exposing Bear.app notes as FS

This plugin contains two storage engines:

1. `bear-db` - generates container manifests for individual notes
2. `bear-note` - a storage for exposing individual note

The macro-container (with `bear-db` storage) will serve manifest files:

```
beardb/
|-- 51B0CB5D-6705-46B7-9FD8-E0DE94920870-43013-00011988990AD515.yaml
|-- 5EE58E7D-34DD-48B5-94F5-E19A1885F81A-43013-00011988993CEF0A.yaml
|-- 7D8A37C8-3954-4D8B-B3B6-854799D550FA-43013-000118623884F695.yaml
|-- A22C756D-D5E7-40CD-AA38-C5B5F9BB7E74-43013-0001198898DBCE51.yaml
`-- F5A8A174-C070-4752-837B-3535C6468A71-43013-0001186237F11107.yaml
```

For the manifest files to be mountable, the storage needs to have `trusted`
manifest flag enabled.

The individual note will be mounted under paths corresponding to its UUID and
tags. For example, if a note contains `welcome` and `welcome/getting started`
tags, it will be mounted under:

```
/.uuid/{uuid}
/welcome
/getting started
```

The note container exposes the following files:

```
README.txt
{uuid}.md       note's body
node.md         note's body (alias)
```


## Initializing and mounting

First, we need to ask WL create the macro-container for exposing BearDB notes:

```
wl container create bear-notes --path /mynotes
wl storage create beardb --container bear-notes \
                         --path /beardb/database.sqlite \
                         --trusted
```

To mount and expose the notes via WL FS tree, one needs to do:
```
wl mount --container bear-notes
wl mount --container ~/wildland/mynotes/*.yaml
```

The first command mounts the macro-container, which contains the
automatically-generated manifests for every Bear note found in the BearDB.

The second command instructs WL client to mount all these micro-containers and
expose them in the filesystem.
