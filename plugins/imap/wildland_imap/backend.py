'''
Wildland storage backend exposing read only IMAP mailbox
'''
import logging
from functools import partial

import click

from wildland.storage_backends.base import StorageBackend
from wildland.storage_backends.generated import \
    GeneratedStorageMixin, FuncFileEntry, FuncDirEntry
from .ImapClient import ImapClient
from .name_helpers import FileNameFormatter, TimelineFormatter
from .TimelineDate import TimelineDate, DatePart


logger = logging.getLogger('storage-imap')



class ImapStorageBackend(GeneratedStorageMixin, StorageBackend):
    '''
    Backend responsible for serving imap mailbox content.
    '''

    TYPE = 'imap'

    def __init__(self, **kwds):
        super().__init__(**kwds)
        self.client = ImapClient(self.params['host'],
                                 self.params['login'],
                                 self.params['password'],
                                 self.params['folder'],
                                 self.params['ssl'])

    def mount(self):
        '''
        mounts the file system
        '''
        self.client.connect()

    def unmount(self):
        '''
        unmounts the filesystem
        '''
        self.client.disconnect()

    def get_root(self):
        '''
        returns wildland entry to the root directory
        '''
        return FuncDirEntry('.', self._root)

    def _root(self):
        '''
        returns statically defined contents of the root directory:
        senders/ - containing list of sender directories
        timeline/ - containing timeline entries for received messages
        '''
        yield FuncDirEntry('senders', self._senders)
        yield FuncDirEntry('timeline', partial(self._timeline_dir,
                                               TimelineDate()))

    def _senders(self):
        '''
        generates contents of senders/ directory
        '''
        for s in self.client.all_senders():
            yield FuncDirEntry(s, partial(self._sender_dir, s))

    def _sender_dir(self, sender_id):
        '''
        Generates the content of sender directory for sender
        with given id (email address). This is effectively
        the listing of email messages.
        '''

        logger.debug('requesting listing for sender %s', sender_id)
        fnf = FileNameFormatter()
        for mid, hdr in self.client.sender_messages(sender_id):
            fn = _filename(hdr)
            logger.debug('message %d resolved to %s', mid, fn)

            yield FuncFileEntry(fnf.format(fn),
                                on_read=partial(self._read_msg,
                                                mid))

    def _timeline_dir(self, parent: TimelineDate):
        '''
        Generates a timeline directory for given "parent" in
        timeline.
        '''
        logger.debug('listing contents of timeline dir %s', parent)
        if parent.accuracy == DatePart.DAY:
            # we're rendering emails here
            fmt = FileNameFormatter()
            for mid, hdr in self.client.mails_at_date(parent):
                fn = _filename(hdr)
                yield FuncFileEntry(fmt.format(fn),
                                    on_read=partial(self._read_msg,
                                                    mid))
        else:
            # Here we render next level of the time scale
            fmt = TimelineFormatter(parent.accuracy.advance())
            for te in self.client.timeline_children(parent):
                yield FuncDirEntry(fmt.format(te),
                                   partial(self._timeline_dir, te))

    def _read_msg(self, msg_id):
        logger.debug('_read_msg called for %d', msg_id)
        return self.client.get_message(msg_id)

    @classmethod
    def cli_options(cls):
        return [
            click.Option(['--host'], metavar='HOST',
                          help='imap server host name',
                          required=True),
            click.Option(['--login'], metavar='LOGIN',
                         help='imap account name / login',
                         required=True),
            click.Option(['--password'], metavar='PASSWORD',
                         help='imap account password',
                         required=True),
            click.Option(['--folder'], metavar='FOLDER',
                         default='INBOX',
                         show_default=True,
                         help='root folder to expose'),
            click.Option(['--ssl/--no-ssl'], metavar='SSL',
                         default=True,
                         show_default=True,
                         help='use encrypted connection')
            ]

    @classmethod
    def cli_create(cls, data):
        return {
            'host': data['host'],
            'login': data['login'],
            'password': data['password'],
            'folder': data['folder'],
            'ssl': data['ssl']
            }


def _filename(hdr) -> str:
    return f'{hdr.sender}-{hdr.subject}'
