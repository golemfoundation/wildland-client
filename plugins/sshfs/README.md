# sshfs storage plugin README

This document provides a brief description of sshfs plugin for
Wildland. 

## Prerequisites

sshfs plugin works as a wrapper, exposing actual sshfs mountpoint
as part of Widlland filesystem. It is assumed that relevant
package needed for sshfs to work is already installed in
system-specific way, i.e.:

- `apt-get install sshfs` for Debian Linux
- download from
  [https://github.com/osxfuse/sshfs/releases/download/osxfuse-sshfs-2.5.0/sshfs-2.5.0.pkg](OSXFUSE)
  site for macOS


## Storage creation

To create storage manifest you need to provide necessasry
parameters so that Wildland can mount an SSHFS filesystem and
properly authentciate with the server. MacOS example could look
like this:

```
/Applications/WildlandClient.app/Contents/MacOS/wl-cli \
  storage create sshfs \
  --container mycontainer \
  --sshfs-command /usr/local/bin/sshfs \
  --host server_name \
  --ssh-user mylogin \
  --pwprompt
```


## Authentication

In order to mount the filesystem, ssh backend needs to
authenticate itself to the SSH server. Currently supported
options are:

### Configure password authentication 
When creating the storage use `--pwprompt` option. You will be
asked to provide the password that will be used to authenticate
`ssh-user`. The password will be stored in the storage manifest.

### Use identity file
Alternatively provide path to private key used for authentication
via `ssh-identity` option. The copy of your key will be stored
with manifest. Note that if key is passphrase-protected you need
to ensure measures (i.e. correctly configured ssh-agent) to
decrypt the key from background process.


## Known issues

### Using sshfs on macOS

To use `sshfs` on macOS you first need to install OSXFUSE. On
first attempt to mount a fuse-based filesystem you will be
requested to grant permission to fuse system extension. Doing so
involves system restart.

### Mount command times out

There can be several reasons for timing out `container mount`
command. One obvious reason is trying to mount it when SSH server
is not reachable. Other reason could be, that you are requesting
connection to a server which is not yet in `~/.ssh/known_hosts`
database (or its identity had changed). To check if this is the
issue, try logging in with ssh to the target host, i.e.:

```
ssh mylogin@server_name 
```


