# Dropbox Dropbox plugin README

This README briefly describes how to use Wildland Dropbox plugin.

### Getting started

Wildland's Dropbox plugin allows to use Dropbox as a read/write storage for Wildland containers. To be able to create Dropbox storage, you need to generate [Dropbox access token][1] that you will pass as a `--token` parameter. Navigate to [Dropbox App Console][2] and select:
- _Create app_,
- _Choose an API_: _Scoped access_ (which is the only option available at the time of writing),
- _Choose the type of access you need_: you can select either _App folder_ or _Full Dropbox_ depending if you want to mount just Wildland-dedicated folder or your whole Dropbox drive respectively,
- _Name your app_: you can pick any name you like.

After following the above steps, you will be navigated to _Settings_ tab. Switch to the _Permissions_ tab and select checkboxes next to the following options:
- files.metadata.write
- files.metadata.read
- files.content.write
- files.content.read

Switch back to _Settings_ tab and under _Access token expiration_ select _No expiration_ instead of _Short-lived_ (see issue [#199](#issue199)). Now you are ready to generate access token that you need to use as a value for `wl storage create --token` option. Under _Generated access token_ label click _Generate_ and make sure to copy the value that will be prompted as it will disappear after navigating away (you will need to generate another access token in this case).

Note that after each modification of the Dropbox permissions (Dropbox _Permissions_ tab in [Dropbox App Console][2]) you need to generate new access token to make newly selected set of permissions active.

### Creating Dropbox storage

If you want to create Dropbox storage use the following command:
```bash
wl storage create dropbox --inline --container test-container-1 --token DROPBOX_ACCESS_TOKEN
```
`--token` parameter specifies your personal Dropbox access token that you generated in the way mentioned above.

### Mounting

The mounting process is no different than any other container.

```bash
wl start
wl c mount MYCONTAINER
```

### Dropbox documentation

* Dropbox App Console: https://www.dropbox.com/developers/apps
* Dropbox Python SDK repository: https://github.com/dropbox/dropbox-sdk-python
* Dropbox Python SDK documentation: https://dropbox-sdk-python.readthedocs.io/en/latest/

### Issues

* Dropbox directories don't have a notion of modification time thus `ls -la` and `stat` commands print modification time set to `1970`.
* <a name="issue199"></a>(issue [#199][3]) Currently in order to setup Dropbox account for Wildland integration, user needs to navigate to [Dropbox App Console][1] to set _Access token_ expiration to _No-expiration_. Dropbox says that _No-expiration_ sessions will be deprecated in some time. We need to implement support for _Short-lived_ sessions.
* (issue [#174][4]) There is a unresolved problem with slow writes to text files with vim. When you open new or existing file with vim, it is loading ~9 seconds. `:wq` (save and quit) takes ~4 seconds to complete. When you append some text to the file with `echo 'some text' >> mnt/file.txt` it works much faster. This may be related to how Vim swap file works. When you run Vim with `-n` parameter, Vim opens instantly but `:wq` is still slow (~4 seconds). This needs further investigation.
* (issue [#179][5]) There is a problem with printing an error `touch: setting times of 'mnt/testdir1/dir_test_01/test3.txt': Function not implemented` when `touch mnt/testdir1/dir_test_01/test3.txt`. Despite printed error, file is created successfully. This issue may relate to `set[x]attr` and `ctime`/`mtime`/`atime`.

[1]: https://www.dropbox.com/lp/developers/reference/oauth-guide
[2]: https://www.dropbox.com/developers/apps
[3]: https://gitlab.com/wildland/wildland-client/-/issues/199
[4]: https://gitlab.com/wildland/wildland-client/-/issues/174
[5]: https://gitlab.com/wildland/wildland-client/-/issues/179
