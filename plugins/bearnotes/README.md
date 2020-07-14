# Wildland backend for exposing Bear.app notes as FS

This plugin contains two storage engines:

1. `bear-db` - generates container manifests for individual notes
2. `bear-note` - a storage for exposing individual note

The macro-container (with `bear-db` storage) will serve manifest files:

```
beardb/
  51B0CB5D-6705-46B7-9FD8-E0DE94920870-43013-00011988990AD515/
    README.txt      - an explanation for this directory
    container.yaml  - a container manifest (including storage specification)
    note.md         - note content (if mounted with with_content option)
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

The note container exposes single a `note-{uuid}.md` file; in the future, it
will also contain attachments.


## Initializing and mounting

First, we need to ask WL create the macro-container for exposing BearDB notes:

```
wl container create bear-notes --path /mynotes
wl storage create beardb --container bear-notes \
                         --path /beardb/database.sqlite \
                         --trusted \
                         --with-content
```

To mount and expose the notes via WL FS tree, one needs to do:
```
wl start
wl container mount bear-notes
wl container mount ~/wildland/mynotes/*/*.yaml
```

The first command mounts the macro-container, which contains the
automatically-generated manifests for every Bear note found in the BearDB.

The second command instructs WL client to mount all these micro-containers and
expose them in the filesystem.
