# Wildland backend for exposing IMAP mailbox as FS

This plugin allows read-only access to IMAPv4 mailbox
folder. Mailbox contents is organized into two separate category
groups:

- **senders**, containing e-mails grouped by senders
- **timeline**, which allows browsing e-mails in timeline
  structure, based on mail receive time.

## Message naming and contents

Each message retrieved from IMAP is represented as a pseudo file,
named according to the following pattern:

`{sender}-{subject}[-{number}]`

where number is added if there is more than one message with the
same name in the directory.

The file content reflects main content of the message, decoded
and represented in plain text form. Attachments, alternative and
multipart messages are not supported.

## Directory structure

Messagesare accessible through the following dynamically
generated riectories:

 - `/timeline/{year}/{month}/{day}/`
 - `/sender/{email}/`

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

## Other implementation details

### Synchronization
Current implementation will naively poll for mailbox changes in
10 second intervals. New messages will be silently added to the
directory structure. Messages deleted or moved from the IMAP
folder will be removed from the file system.

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
  mailbox folder which needs to be exposed.
