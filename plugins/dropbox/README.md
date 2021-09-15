# Dropbox plugin README

This README briefly describes how to use Wildland Dropbox plugin.

### Getting started

Wildland Dropbox plugin allows using Dropbox as a read/write storage for Wildland containers. To be able to create
Dropbox storage, navigate to [Dropbox App Console][1] and select:

- _Create app_,
- _Choose an API_: _Scoped access_, which is the only option available at the time of writing,
- _Choose the type of access you need_: you can select either _App folder_ or _Full Dropbox_ depending if you want to mount just Wildland-dedicated folder or your whole Dropbox drive respectively,
- _Name your app_: you can pick any name you like.

After following the above steps, you have access to your application key `App Key` under _Settings_ tab.
Then, switch to the _Permissions_ tab and select checkboxes next to the following options:

- `files.metadata.write`
- `files.metadata.read`
- `files.content.write`
- `files.content.read`

Now you are ready to create Dropbox container.

> Note: After each modification of the Dropbox permissions (Dropbox _Permissions_ tab in [Dropbox App Console][1]),
you need to generate new refresh token to make newly selected set of permissions active.

### Creating Dropbox storage

If you want to create Dropbox storage use the following command:

```bash
wl storage create dropbox --inline \
                          --container test-container-1 \
                          --app-key INSERT_YOUR_APP_KEY_HERE_IN_BETWEEN_SINGLE_QUOTES
```

You will be asked to open a URL. Open this URL to login your Dropbox account and then, allow the request. Finally, 
copy and paste the generated access code inside the console.

If you want to skip this procedure of opening a URL and logging into your Dropbox account, you need to provide
the `refresh_token` value (see [Dropbox refresh token][2] for details on how to get it) to `--refresh-token`:

```bash
wl storage create dropbox --inline \
                          --container test-container-1 \
                          --app-key INSERT_YOUR_APP_KEY_HERE_IN_BETWEEN_SINGLE_QUOTES \
                          --refresh-token INSERT_YOUR_REFRESH_TOKEN_HERE_IN_BETWEEN_SINGLE_QUOTES
```

### Mounting

The mounting process is no different than any other container.

```bash
wl start
wl c mount MYCONTAINER
```

### Dropbox documentation

* Dropbox App Console:\
  `https://www.dropbox.com/developers/apps`
* Dropbox Python SDK repository:\
  `https://github.com/dropbox/dropbox-sdk-python`
* Dropbox Python SDK documentation:\
  `https://dropbox-sdk-python.readthedocs.io/en/latest/`

### Issues

* Dropbox directories don't have a notion of modification time thus `ls -la` and `stat` commands print modification time set to `1970`.
* <a name="issue199"></a>[issue [#199][3]] Currently in order to setup Dropbox account for Wildland integration, user needs to navigate to [Dropbox App Console][2] to set _Access token_ expiration to _No-expiration_. Dropbox says that _No-expiration_ sessions will be deprecated in some time. We need to implement support for _Short-lived_ sessions.
* (issue [#174][4]) There is a unresolved problem with slow writes to text files with vim. When you open new or existing file with vim, it is loading ~9 seconds. `:wq` (save and quit) takes ~4 seconds to complete. When you append some text to the file with `echo 'some text' >> mnt/file.txt` it works much faster. This may be related to how Vim swap file works. When you run Vim with `-n` parameter, Vim opens instantly but `:wq` is still slow (~4 seconds). This needs further investigation.

[1]: https://www.dropbox.com/developers/apps
[2]: https://www.dropbox.com/lp/developers/reference/oauth-guide
[3]: https://gitlab.com/wildland/wildland-client/-/issues/199
[4]: https://gitlab.com/wildland/wildland-client/-/issues/174
