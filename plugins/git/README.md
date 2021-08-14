# Git plugin

This is a plugin that allows to expose git repositories as wildland containers with read-only access. 

### Getting started

The automatic re-cloning of the repository happens upon every mount of the container. Because of this, it's recommended to provide your username and the access token to the backend upon creating the storage.
However, if you prefer not to make the credentials visible in the bash history/storage manifest, you can choose not to provide them to the backend. In this case, you will be asked to provide the credentials upon every mount of the storage as they are necessary in order to clone the repository. 

### Creating the container

Creating a container for your repository is no different than creating containers for any of the other backends. It can be done by using the following command:

```
wl container create MYCONTAINER --path /git
```

Because of the `--path` parameter, your container will be visible under the `/wildland/git` directory. 

### Creating Git storage

To create the storage, use the following command:

```
wl storage create git --container MYCONTAINER \
                        --url URL_TO_REPO \
                        [--username <username>] \
                        [--password <password>]
```
`--url` parameter specifies the url to the git repository you wish to clone and should be following the `http[s]://host.xz[:port]/path/to/repo.git` syntax.
`--username` optional parameter specifies the username and will be needed whenever you attempt to clone a private repository. If you choose to provide it (along with the password/token parameter), the default authorization with a prompt will be skipped. 
`--password` parameter specifies the password/token you choose to use for authorization purposes. 
You can find out how to create your own personal token for [GitLab][1] or [GitHub][2] here.

### Mounting

To mount the container you created, use the following command:

```
wl container mount MYCONTAINER
```

Upon each mount of the container, the previously cloned version of the repository (if one exists) is removed so that an up to date version of the repo can be cloned. Because of this, whenever you want to fetch any new commits from the remote repo, you simply need to remount the container.

### GitPython documentation:

This plugin uses the GitPython module. More information about the module can be found here:
[https://gitpython.readthedocs.io/en/stable/][3]

[1]: https://docs.gitlab.com/ee/user/profile/personal_access_tokens.html#create-a-personal-access-token
[2]: https://docs.github.com/en/github/authenticating-to-github/keeping-your-account-and-data-secure/creating-a-personal-access-token
[3]: https://gitpython.readthedocs.io/en/stable/
