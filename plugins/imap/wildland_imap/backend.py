'''
Wildland storage backend exposing read only IMAP mailbox
'''
import logging
from functools import partial
from pathlib import PurePosixPath
from typing import Iterable, List, Set
from datetime import timezone

import uuid
import click

from wildland.storage_backends.base import StorageBackend
from wildland.storage_backends.watch import SimpleStorageWatcher
from wildland.storage_backends.generated import \
    GeneratedStorageMixin, FuncFileEntry, FuncDirEntry
from .ImapClient import ImapClient, MessageEnvelopeData, \
    MessagePart

logger = logging.getLogger('storage-imap')

class ImapStorageWatcher(SimpleStorageWatcher):
    '''
    A watcher for IMAP server. This implementation just queries
    the server and reports an update if message list has changed.
    '''

    def __init__(self, backend: 'ImapStorageBackend'):
        super().__init__(backend)
        self.client = backend.client

    def get_token(self):
        return self.client.refresh_if_needed()

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

    def watcher(self):
        return ImapStorageWatcher(self)

    def list_subcontainers(self) -> Iterable[dict]:
        for msg in self.client.all_messages_env():
            yield self._make_msg_container(msg)

    def get_root(self):
        '''
        returns wildland entry to the root directory
        '''
        return FuncDirEntry('.', self._root)

    def _root(self):
        logger.info("_root() requested for %s", self.backend_id)
        for envelope in self.client.all_messages_env():
            yield FuncDirEntry(self._id_for_message(envelope),
                               partial(self._msg_contents,
                                       envelope))

    def _msg_contents(self, e: MessageEnvelopeData):
        # This little method should populate the message directory
        # with message parts decomposed into MIME attachements.
        for part in self.client.get_message(e.msg_uid):
            yield FuncFileEntry(part.attachment_name,
                                on_read=partial(self._read_part,
                                                part),
                                timestamp=e.recv_t.replace(tzinfo=timezone.utc).timestamp())

    def _read_part(self, msg_part: MessagePart) -> bytes:
        # pylint: disable=no-self-use
        return msg_part.content

    def _get_message_categories(self, e: MessageEnvelopeData) -> List[str]:
        '''
        Generate the list of category paths that the message will
        appear under.
        '''
        rv: Set[PurePosixPath] = set()

        # entry in timeline
        rv.add(PurePosixPath('/timeline') /
               PurePosixPath('%04d' % e.recv_t.year) /
               PurePosixPath('%02d' % e.recv_t.month) /
               PurePosixPath('%02d' % e.recv_t.day))

        # (static) entry in folder path
        rv.add(PurePosixPath('/folder') /
               PurePosixPath(self.params['folder']))

        # email address tagging
        bp = PurePosixPath('/users')
        for s in e.senders:
            rv.add(bp / PurePosixPath(s) / PurePosixPath('sender'))
        for r in e.recipients:
            rv.add(bp / PurePosixPath(r) / PurePosixPath('recipient'))

        return sorted(str(p) for p in rv)

    def _id_for_message(self, env: MessageEnvelopeData) -> str:
        '''
        returns a string representation of stable uuid identifying
        email message of which the envelope is given.
        '''
        ns = uuid.UUID(self.backend_id)
        return str(uuid.uuid3(ns, str(env.msg_uid)))


    def _make_msg_container(self, env: MessageEnvelopeData) -> dict:
        '''
        Create a container manifest for a single mail message.
        '''
        ident = self._id_for_message(env)
        paths = [f'/.uuid/{ident}']
        logger.debug('making msg container for msg %d as %s',
                     env.msg_uid, ident)
        categories = self._get_message_categories(env)
        return {
            'paths': paths,
            'title': f'{env.subject} - {ident}',
            'categories': categories,
            'backends': {'storage': [{
                'type': 'delegate',
                'reference-container': 'wildland:@default:@parent-container:',
                'subdirectory': '/' + ident
                }]}
        }


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
