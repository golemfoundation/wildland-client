# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
#                    Piotr K. Isajew <pki@ex.com.pl>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Wildland storage backend exposing read only IMAP mailbox
"""
from functools import partial
from pathlib import PurePosixPath
from typing import Iterable, List, Set, Tuple, Optional
from datetime import timezone

import uuid
import click

from wildland.storage_backends.base import StorageBackend
from wildland.storage_backends.watch import SimpleFileWatcher, SimpleSubcontainerWatcher
from wildland.storage_backends.generated import \
    GeneratedStorageMixin, StaticFileEntry, FuncDirEntry
from wildland.container import ContainerStub
from wildland.log import get_logger
from .ImapClient import ImapClient, MessageEnvelopeData, MessagePart

logger = get_logger('storage-imap')


class ImapStorageWatcher(SimpleFileWatcher):
    """
    A watcher for IMAP server. This implementation just queries
    the server and reports an update if message list has changed.
    """

    def __init__(self, backend: 'ImapStorageBackend'):
        super().__init__(backend)
        self.client = backend.client

    def get_token(self):
        return self.client.refresh_if_needed()


class ImapSubcontainerWatcher(SimpleSubcontainerWatcher):
    """
    A watcher for IMAP server. This implementation just queries
    the server and reports an update if message list has changed.
    """

    def __init__(self, backend: 'ImapStorageBackend'):
        super().__init__(backend)
        self.client = backend.client

    def get_token(self):
        return self.client.refresh_if_needed()


class ImapStorageBackend(GeneratedStorageMixin, StorageBackend):
    """
    Backend responsible for serving imap mailbox content.
    """

    TYPE = 'imap'
    LOCATION_PARAM = 'folder'

    def __init__(self, **kwds):
        super().__init__(**kwds)
        self.read_only = True
        self.client = ImapClient(self.persistent_db,
                                 self.params['host'],
                                 self.params['login'],
                                 self.params['password'],
                                 self.params['folder'],
                                 self.params['ssl'])

    def mount(self):
        """
        Mounts the filesystem.
        """
        self.client.connect()

    def unmount(self):
        """
        Unmounts the filesystem.
        """
        self.client.disconnect()

    def watcher(self):
        return ImapStorageWatcher(self)

    def subcontainer_watcher(self):
        return ImapSubcontainerWatcher(self)

    @property
    def can_have_children(self) -> bool:
        return True

    def get_children(
            self,
            client=None,
            query_path: PurePosixPath = PurePosixPath('*'),
            paths_only: bool = False
    ) -> Iterable[Tuple[PurePosixPath, Optional[ContainerStub]]]:
        for envelope in self.client.all_envelopes():
            yield self._make_msg_container(envelope, paths_only)

    def get_root(self):
        """
        Returns Wildland entry of the root directory.
        """
        return FuncDirEntry('.', self._root)

    def _root(self):
        logger.debug("_root() requested for %s", self.backend_id)
        for envelope in self.client.all_envelopes():
            yield FuncDirEntry(self._id_for_message(envelope),
                               partial(self._msg_contents, envelope),
                               int(envelope.recv_time.replace(tzinfo=timezone.utc).timestamp()))

    def _msg_contents(self, e: MessageEnvelopeData):
        # This little method should populate the message directory
        # with message parts decomposed into MIME attachments.
        for part in self.client.get_message(e.msg_uid):
            yield StaticFileEntry(part.attachment_name,
                                  part.content,
                                  int(e.recv_time.replace(tzinfo=timezone.utc).timestamp()))

    def _read_part(self, msg_part: MessagePart) -> bytes:
        # pylint: disable=no-self-use
        return msg_part.content

    def _get_message_categories(self, e: MessageEnvelopeData) -> List[str]:
        """
        Generate the list of category paths that the message will appear under.
        """
        rv: Set[PurePosixPath] = set()

        # entry in timeline
        rv.add(PurePosixPath('/timeline') /
               PurePosixPath('%04d' % e.recv_time.year) /
               PurePosixPath('%02d' % e.recv_time.month) /
               PurePosixPath('%02d' % e.recv_time.day))

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
        """
        returns a string representation of stable uuid identifying
        email message of which the envelope is given.
        """
        ns = uuid.UUID(self.backend_id)
        return str(uuid.uuid3(ns, str(env.msg_uid)))

    def _make_msg_container(self, env: MessageEnvelopeData, paths_only: bool) \
            -> Tuple[PurePosixPath, Optional[ContainerStub]]:
        """
        Create a container manifest for a single mail message.
        """
        ident = self._id_for_message(env)
        paths = [f'/.uuid/{ident}']
        logger.debug('making msg container for msg %d as %s', env.msg_uid, ident)
        categories = self._get_message_categories(env)
        subcontainer_path = '/' + ident
        if not paths_only:
            return PurePosixPath(subcontainer_path), ContainerStub({
                'paths': paths,
                'title': f'{env.subject} - {ident}',
                'categories': categories,
                'backends': {'storage': [{
                    'type': 'delegate',
                    'reference-container': 'wildland:@default:@parent-container:',
                    'subdirectory': subcontainer_path
                }]}
            })
        return PurePosixPath(subcontainer_path), None

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
                         help='imap account password (omit for a password prompt)',
                         prompt=True, required=True, hide_input=True),
            click.Option(['--folder'], metavar='FOLDER',
                         default='INBOX',
                         help='root folder to expose'),
            click.Option(['--ssl/--no-ssl'], metavar='SSL',
                         default=True,
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
