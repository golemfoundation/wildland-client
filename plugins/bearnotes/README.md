# Wildland backend for exposing Bear.app notes as FS

This plugin exposes individual notes from the [Bear App](https://bear.app/) as a number of sub-containers.

Each individual note will be mounted under categories corresponding to its tags (as well as under the path based on the note's unique identifier). For example, if a note titled `Wildland Project` contains `#topics/projects` and `#actors/orgs/Golem Foundation` tags, it will be exposed as:

```
/.uuid/{note's UUID}
/topics/projects/"Wildland Project"
/actors/orgs/Golem Foundation/"Wildland Project"
```

In addition, it will also be exposed via the synthetic @-dirs (as any other Wildland container):

```
/topics/projects/@actors/orgs/Golem Foundation/"Wildland Project"
/actors/orgs/Golem Foundation/@topics/projects/"Wildland Project"
```

## Quoting and sanitization of the note's titles

Note the quoting of the note's title (last part of the path) in the examples above. The rationale for this is that otherwise the user would see notes intermixed with tags. This makes the note's projection into the FS messy.

Consider the following example:

```
/places/Poland/
 `- Krakow    --> a tag further refining the classification
 `- Some Note --> a leaf representing a note tagged as #places/Poland
 `- Warsaw    --> another tag refining the classification

```

When we prepend all the notes with a `"`" than the above situation gets more tidy, as the `"`-prefixed directories will typically be sorted before non-quoted directories by most file managers.

In addition, any occurrence of the slash character (`/`) is replaced with the underscore (`_`) in the note's title. This is to avoid creation of unintended nested directories.

## The note-representing container content

The directory representing the note contains the following files:
- a single `note.md` file representing the (Markdown) body of the note,
- any attachments the note might be referring to from its body (NOTE: currently not implemented)

## Setup and use

To create the macro-container for exposing Bear notes:

```
wl container create bear-notes --path /mynotes
wl storage create bear-db --container bear-notes --path /beardb/database.sqlite
```

To expose (mount) all the notes, simply mount the macro-container:

```
wl container mount bear-notes
```

## Limitations

- This backend is Read-Only. This means that both the note's content cannot be edited, as well as that any modification to the note's categories are not possible (this latter property really is a consequence of the former, since in Bear App it is always the note's body that dictates what categories the note is assigned too).

- Attachments are not exposed in the note's container

- Currently `mount-watch` doesn't work for sub-containers, thus after every modification of the Bear's database (such as after creating or updating of any note), one needs to re-mount the macro container.

- The backend must have access to the Bear's internal SQLite, which must be exposed to it somehow. Typically we assume that the client runs on the same (macOS) host where the Bear App is used. If this is not the case, then the corresponding SQLite file must be somehow made available to the Bear backend. This might be done using some other Wildland backend, such as e.g. Dropbox, S3 or WebDAV.

- The `pybear` python library which is used to extract the notes from the Bear's SQLite DB is non-official. Bear does not publish official API for reading the notes from its internal DB.
