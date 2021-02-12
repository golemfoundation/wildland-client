# Dropbox Readme

Dropbox backend for Wildland client. Allows to use Dropbox as a read-write storage for WL containers.

### Getting started

If you want to create Dropbox storage use the following command:
```bash
wl storage create dropbox --inline --container test-container-1 --token DROPBOX_ACCESS_TOKEN
```
`--token` parameter specifies your personal Dropbox access token that you can generate in Dropbox App Console (https://www.dropbox.com/developers/apps).

### Mounting

The mounting process is no different than any other container.

```bash
wl start
wl c mount MYCONTAINER
```

### Dropbox documentation

* Dropbox Python SDK repository: https://github.com/dropbox/dropbox-sdk-python
* Dropbox Python SDK documentation: https://dropbox-sdk-python.readthedocs.io/en/latest/

### Issues

* Dropbox directories don't have a notion of modification time thus `ls -la` and `stat` commands print modification time set to 1970.
* (issue #174) There is a unresolved problem with slow writes to text files with vim. When you open new or existing file with vim, it is loading ~9 seconds. `:wq` (save and quit) takes ~4 seconds to complete. When you append some text to the file with `echo 'some text' >> mnt/file.txt` it works much faster. This may be related to how Vim swap file works. When you run Vim with `-n` parameter, Vim opens instantly but `:wq` is still slow (~4 seconds). This needs further investigation.
* (issue #179) There is a problem with printing an error `touch: setting times of 'mnt/testdir1/dir_test_01/test3.txt': Function not implemented` when `touch mnt/testdir1/dir_test_01/test3.txt`. Despite printed error, file is created successfully. This issue may relate to `set[x]attr` and `ctime`/`mtime`/`atime`.
