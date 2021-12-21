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
ImapClient is a module delivering an IMAP mailbox representation
for wildland imap backend. The representation is read-only,
update-sensitive and includes primitive caching support.
"""
import locale
import time
import mimetypes
import imaplib
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from email.header import decode_header
from email.message import Message
from email.parser import BytesParser
from email import policy
from threading import Lock
from typing import List, Set, Dict, Tuple, Iterable

from imapclient import IMAPClient
from imapclient.response_types import Envelope, Address

from wildland.log import get_logger
from wildland.storage_backends.kv_store import KVStore


@dataclass(eq=True, frozen=True)
class MessageEnvelopeData:
    """
    Compact representation of e-mail header, as we use it
    for processing internally.
    """
    msg_uid: str
    # Note, that here a simplified approach is used, compared to
    # RFC5322, which assigns slightly different semantics to From
    # and Sender headers. Here we just collect every Sender/From
    # element and expose it as part of sender list.
    senders: List[str]
    # Again, we do not differentiate between To and Cc fields.
    recipients: List[str]
    subject: str
    recv_time: datetime


@dataclass(eq=True, frozen=True)
class MessagePart:
    """
    DTO for message attachement / mime part of the message.
    """
    attachment_name: str
    mime_type: str
    content: bytes


class LocalCache:
    """
    Local cached data needed to construct the FS structure.
    """

    def __init__(self, db: KVStore):
        self.db = db
        self.msg_ids: Set[str] = set()

    def get_ids(self):
        """
        Get all message IDs from cached storage.
        """
        self.msg_ids = self.db.get_all_keys()

    def add_msg(self, msg_id: str, envelope: MessageEnvelopeData):
        """
        Add a message to cached storage.
        """
        self.db.store_object(msg_id, envelope)
        self.msg_ids.add(msg_id)

    def get_msg(self, msg_id: str) -> MessageEnvelopeData:
        """
        Get a message from cached storage.
        """
        return self.db.get_object(msg_id)

    def del_msg(self, msg_id: str):
        """
        Delete a message from cached storage.
        """
        self.msg_ids.remove(msg_id)
        self.db.del_object(msg_id)


class ImapClient:
    """
    IMAP protocol client implementation adding some additional
    level of abstraction over generic IMAPClient to expose
    the features needed by the wildland filesystem.
    """

    # Avoid querying the server more often than that (seconds):
    QUERY_INTERVAL = 60

    def __init__(self, backend_db: KVStore, host: str, login: str, password: str, folder: str,
                 ssl: bool):
        self.logger = get_logger('ImapClient')
        self.host = host
        self.ssl = ssl
        self.imap = None
        self.login = login
        self.password = password
        self.folder = folder
        self._envelope_cache = LocalCache(backend_db)

        # message id: message contents (only populated when message content is requested)
        self._message_cache: Dict[str, List[MessagePart]] = dict()

        # lock guarding access to local data structures
        self._local_lock = Lock()

        # monitor thread monitors changes to the inbox and updates the cache accordingly
        self._connected = False

        # lock guarding access to imap client
        self._imap_lock = Lock()

        # to keep track of remote changes:
        self._mailbox_version = 0
        self._last_mailbox_query = 0

    def connect(self):
        """
        Connect to IMAP server.
        """
        self.logger.debug('connecting to IMAP server')
        self.imap = IMAPClient(self.host, use_uid=True, ssl=self.ssl)

        assert self.imap is not None

        self.imap.login(self.login, self.password)
        self.imap.select_folder(self.folder, True)
        self._message_cache = dict()
        self._mailbox_version = 0
        self._last_mailbox_query = 0
        self._envelope_cache.get_ids()

        self._connected = True
        self.logger.debug('connected to IMAP server %s', self.host)

    def disconnect(self):
        """
        Disconnect from IMAP server.
        """
        with self._local_lock:
            self.logger.debug('disconnecting from IMAP server')
            if self._connected:
                self._connected = False
                with self._imap_lock:
                    assert self.imap is not None

                    self.imap.logout()
                    # Note that there is a bug in current IMAPClient code, which makes it
                    # impossible to reuse the object to log in again after logout.
                    # That's why we dereference it here, and get a fresh instance on connect.
                    self.imap = None
                self.logger.debug("ImapClient disconnected")

    def all_envelopes(self) -> Iterable[MessageEnvelopeData]:
        """
        Provides iterable over collection of all envelopes fetched from server.
        """
        self.refresh_if_needed()

        with self._local_lock:
            for msg_id in self._envelope_cache.msg_ids:
                yield self._envelope_cache.get_msg(msg_id)

    def refresh_if_needed(self) -> int:
        """
        A naive mailbox refresh. Calling it pings the server with NOOP
        and returns a "version" of mailbox observed. Version is just a
        counter incremented each time when mailbox change is detected.
        """
        with self._local_lock:
            if (self._connected and time.time() > self._last_mailbox_query
               + ImapClient.QUERY_INTERVAL):
                with self._imap_lock:
                    self.logger.debug('querying IMAP server')
                    again = True
                    repeats = 3
                    while again:
                        try:
                            assert self.imap is not None

                            reply: Tuple[int, List[Tuple[str, ...]]] = self.imap.noop()
                            again = False
                        except (ConnectionResetError, imaplib.IMAP4.abort):
                            if repeats > 0:
                                repeats -= 1
                                self.logger.debug('connection lost, trying to reconnect')
                                self.connect()
                            else:
                                raise

                    self._last_mailbox_query = int(time.time())
                    if len(reply) > 1:
                        try:
                            self._invalidate_and_reread()
                        except Exception:
                            self.logger.error("exception when refereshing mailbox", exc_info=True)
                    else:
                        self.logger.warning('unknown response received: %s', reply)
            return self._mailbox_version

    def get_message(self, msg_id: str) -> List[MessagePart]:
        """
        Read and return single message (basic headers and main contents) as byte array.
        """
        self.logger.debug('get_message called for: %s', msg_id)
        with self._local_lock:
            if msg_id not in self._message_cache:
                self._message_cache[msg_id] = self._load_msg(msg_id)
            rv = self._message_cache[msg_id]

        return rv

    def _load_raw_message(self, msg_id: str) -> Message:
        """
        Load a message with given identifier from IMAP server.
        _imap_lock must be held.
        """

        self.logger.debug('fetching message %s', msg_id)

        assert self.imap is not None
        data = self.imap.fetch([msg_id], 'RFC822')

        parser = BytesParser(policy=policy.default)
        msg = parser.parsebytes(data[msg_id][b'RFC822'])
        return msg

    def _load_msg(self, msg_id: str) -> List[MessagePart]:
        """
        Load a message with given identifier from IMAP server and return it as a "pretty string".
        """
        rv: List[MessagePart] = list()

        msg = self._load_raw_message(msg_id)

        # msg is actually of type EmailMessage, but parser.parsebytes signature returns Message...
        body = msg.get_body(('html', 'plain'))  # type: ignore
        if body:
            # get_payload() returns bytes or str depending if the message is multipart
            content = body.get_payload(decode=True)

            if content is str:
                charset = body.get_content_charset()
                if not charset:
                    charset = 'utf-8'
                content = bytes(content, charset)
        else:
            content = b'This message contains no decodable body part.'

        ctype = body.get_content_type()
        rv.append(MessagePart('main_body' + (mimetypes.guess_extension(ctype) or ''),
                              ctype,
                              content))

        for att in msg.iter_attachments():  # type: ignore
            content = att.get_payload(decode=True)
            charset = att.get_content_charset()
            if not charset:
                charset = 'utf-8'
            if content is str:
                content = bytes(content, charset)
            filename = att.get_filename() or str(uuid.uuid4())

            part = MessagePart(filename, att.get_content_type(), content)
            rv.append(part)

        return rv

    def _del_msg(self, msg_id: str):
        """
        Remove message from local cache.
        """
        self._envelope_cache.del_msg(msg_id)

        if msg_id in self._message_cache:
            del self._message_cache[msg_id]

    def _prefetch_msg(self, msg_id: str):
        """
        Fetch headers of given message and register them in cache.
        """
        assert self.imap is not None
        data = self.imap.fetch([msg_id], 'ENVELOPE')
        env = data[msg_id][b'ENVELOPE']
        self._register_envelope(msg_id, env)

    def _parse_address(self, addr: Address) -> Set[str]:
        """
        Parse address object tuple (as described in
        https://imapclient.readthedocs.io/en/2.1.0/api.html#imapclient.response_types.Address)
        and return a string suitable for usage as a path element.
        """
        # pylint: disable=no-self-use

        rv: Set[str] = set()

        if addr is None:
            return rv

        for a in addr:
            txt = None
            if a.mailbox:
                txt = a.mailbox.decode()
                if a.host:
                    txt += '@' + a.host.decode()
            elif a.name:
                txt = decode_header(a.name.decode())

            if txt:
                rv.add(_decode_text(txt))

        return rv

    @staticmethod
    @contextmanager
    def _setlocale(loc: str):
        """
        Context for temporary locale change.
        Not thread-safe, _local_lock must be held.
        """
        saved = locale.setlocale(locale.LC_ALL)
        try:
            yield locale.setlocale(locale.LC_ALL, loc)
        finally:
            locale.setlocale(locale.LC_ALL, saved)

    def _register_envelope(self, msg_id: str, env: Envelope):
        """
        Create sender and timeline cache entries, based on raw envelope of received message.
        """

        invalid_chars = {'\0', '/', '\n'}
        senders = set()
        for addr in [env.sender, env.from_]:
            senders |= self._parse_address(addr)

        if not env.subject:
            subject = '<NO SUBJECT>'
        else:
            try:
                sub = decode_header(env.subject.decode())
                subject = _decode_text(sub)
            except UnicodeDecodeError:
                self.logger.exception('Failed to decode subject:')
                subject = str(env.subject)  # fall back to just interpret it as a string

            for c in invalid_chars:
                subject = subject.replace(c, '_')

        recv_time = env.date
        if not recv_time:
            # IMAP envelope contains no timestamp, try to read one from actual mail header
            msg = self._load_raw_message(msg_id)
            # We need the C locale because the format string below contains locale-dependant
            # month name and current thread locale may not be what's expected (C).
            with self._setlocale('C'):
                try:
                    recv_time = datetime.strptime(msg['Delivery-date'],
                                                  '%a, %d %b %Y %H:%M:%S %z')
                except (ValueError, TypeError):
                    # failed to parse, need some default value
                    recv_time = datetime.fromtimestamp(0)

        recipients = set()
        for addr in [env.to, env.cc, env.bcc]:
            recipients |= self._parse_address(addr)

        hdr = MessageEnvelopeData(msg_id, list(senders), list(recipients), subject, recv_time)
        self._envelope_cache.add_msg(msg_id, hdr)

    def _invalidate_and_reread(self):
        """
        Invalidate local message list. Reread and update index.
        """
        assert self.imap is not None
        srv_msg_ids = set(self.imap.search('ALL'))
        cached_ids = self._envelope_cache.msg_ids
        ids_to_remove = cached_ids - srv_msg_ids
        ids_to_add = srv_msg_ids - cached_ids
        self.logger.debug('invalidate: cached %d, server %d, remove %d, add %d',
                          len(cached_ids), len(srv_msg_ids), len(ids_to_remove), len(ids_to_add))

        for mid in ids_to_remove:
            self._del_msg(mid)

        for mid in ids_to_add:
            self._prefetch_msg(mid)

        if len(ids_to_remove) + len(ids_to_add) > 0:
            self._mailbox_version += 1


def _decode_text(encoded) -> str:
    if isinstance(encoded, str):
        rv = encoded
    else:
        rv = ''
        for (subject, charset) in encoded:
            if isinstance(subject, str):
                rv += subject
            else:
                if not charset:
                    charset = 'utf-8'
                rv += subject.decode(charset)
    return rv
