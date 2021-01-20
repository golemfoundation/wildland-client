# Wildland backend for exposing IMAP mailbox as FS

This plugin allows read-only access to IMAPv4 mailbox
folder. Mailbox contents is exposed as separate directories, so
that each e-mail message has it's own directory. 

## Message naming and contents

Each message retrieved from IMAP is identified represented as a
separate directory. The contents of this directory are files
representing:

- main contents (body) of the message
- direct attachements of the message

Each file has a modification time equal to value of `Date` header
of the message.

Directory name is in essence an UUID identifying the message. The
directory is populated as described below.

### Main contents (body) of the message
The backend tries to identify the main contents of the message
and expose it in a file named `main_body.{htm|txt}`. In case of
`multipart/alternative` MIME messages it treats the html part as
main content, if available, or falls back to plain text
otherwise.

File extension for the file representing main contents is guessed
according to the corresponding MIME type.

### Direct attachments of the message

Any attachments of the message (i.e. `Content-Disposition` header is
set to `attachment`) are made available in the message directory
as files named according to `Content-Disposition` header
(i.e. using value of `filename` attribute.

## Support for Wildland subcontainers

The backend can expose individual messages as subcontainers. If
container is mounted using `--with-subcontainers` option, for
each of messages a corresponding subcontainer will be created.

A message container `title` is set to a `{subject} - {id}` where
_subject_ is the subject of the message and _id_ is it's unique
identifier.

Additionally, message container is assigned to categories as
follows:

- `/timeline/{year}/{month}/{day}/` - corresponding to the date
  of the message
- `/folder/{IMAP Folder}/` - an imap folder, from which message
  was retrieved
- `/users/{email-or-name}/sender` - for each address appearing in
  `From` or `Sender` headers
- `/users/{email-or-name}/recipient` - for each address
  appearing in `To` or `Cc` headers


## Initializing and mounting

You need to create a container in which the backend is going to
be mounted:

```
wl container create mail --path /mail
```

The next step is to create a backend associated with your IMAP
account. Note that current implementation stores access
credentials in unencrypted form and relies on operating system to
provide needed security. You are strongly advised to use
separate access cretendials with limited privileges.


```
wl storage create imap --container mail \
                       --host <imap_server> \
                       --login <login> \
                       --password <password> \
                       [--folder <imap_folder>]
```

Once the backend is exposed to container, it can be mounted:

```
wl start
wl container mount mail
```

or 

```
wl start
wl container mount --with-subcontainers mail
```


## Other implementation details

### Synchronization
Whenever a root directory is accessed, the backend will recheck
the corresponding IMAP folder for changes (actually, due to
performance considerations this is limited to 1 query per
minute). If changes are detected, the contents of file system is
updated accordingly.

### Message retrieval and caching
Message contents will be retrieved on first access, what may
cause slight delays. After message is first retrieved it's main
contents is cached in RAM in decoded form.

### Things to improve
- polling interval could be configurable,
- message cache could use some invalidation strategy (i.e. LRU)
  to conserve memory,
- browsing through multiple folders is not supported yet (this
  can be mitigated by configuring separate backend for every
  mailbox folder which needs to be exposed,
- the backend does not offer very good support for HTML messages
  using `cid` URL schemes (see RFC 2392). One could envision that
  future version of the backend would be able to expose
  message parts with `Content-ID` identifiers assigned as files
  in the meessage directory and rewrite references in HTML body
  accordingly,
- no support for digitally signed and/or encrypted e-mails is
  available.
  
