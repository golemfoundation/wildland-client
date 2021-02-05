'''
ImapClient is a module delivering an IMAP mailbox representation
for wildland imap backend. The representation is read-only,
update-sensitive and includes primitive caching support.
'''

import logging
import time
import mimetypes
import imaplib
from dataclasses import dataclass
from threading import Lock
from typing import List, Set
from email.header import decode_header
from email.parser import BytesParser
from email import policy
from datetime import datetime
from imapclient import IMAPClient

@dataclass(eq=True, frozen=True)
class MessageEnvelopeData:
    '''
    Compact representation of e-mail header, as we use it
    for processing internally.
    '''
    msg_uid: int
    # Note, that here a simplified approach is used, compared to
    # RFC5322, which assigns slightly different semantics to From
    # and Sender headers. Here we just collect every Sender/From
    # element and expose it as part of sender list.
    senders: List[str]
    # Again, we do not differentiate between To and Cc fields.
    recipients: List[str]
    subject: str
    recv_t: datetime

@dataclass(eq=True, frozen=True)
class MessagePart:
    '''
    DTO for message attachement / mime part of the message.
    '''
    attachment_name: str # can be None
    mime_type: str
    content: bytes

class ImapClient:
    '''
    IMAP protocol client implementation adding some additional
    level of abstraction over generic IMAPClient to expose
    the features needed by the wildland filesystem.
    '''

    # Avoid querying the server more often than that:
    QUERY_INTERVAL = 60

    def __init__(self, host: str, login: str, password: str,
                 folder: str, ssl: bool):
        self.logger = logging.getLogger('ImapClient')
        self.host = host
        self.ssl = ssl
        self.imap = None
        self.login = login
        self.password = password
        self.folder = folder
        self._envelope_cache = dict()

        # message id: message contents (only populated, when
        # messge content is requested)
        self._message_cache = dict()

        # all ids retrieved
        self._all_ids = set()

        # lock guarding access to local data structures
        self._local_lock = Lock()

        # monitor thread monitors changes to the inbox and
        # updates the cache accordingly
        self._connected = False

        # lock guarding access to imap client
        self._imap_lock = Lock()

        # to keep track of remote changes:
        self._mailbox_version = 0
        self._last_mailbox_query = 0


    def connect(self):
        '''
        Connect to IMAP server.
        '''
        self.logger.debug('connecting to IMAP server')
        self.imap = IMAPClient(self.host, use_uid=True, ssl=self.ssl)
        self.imap.login(self.login, self.password)
        self.imap.select_folder(self.folder, True)
        self._envelope_cache = dict()
        self._message_cache = dict()
        self._all_ids = set()
        self._mailbox_version = 0
        self._last_mailbox_query = 0

        self._connected = True
        self.logger.debug('connected to IMAP server %s', self.host)

    def disconnect(self):
        '''
        disconnect from IMAP server.
        '''
        with self._local_lock:
            self.logger.debug('disconnecting from IMAP server')
            if self._connected:
                self._connected = False
                with self._imap_lock:
                    self.imap.logout()
                    # note that there is a bug in current
                    # IMAPClient code, which makes it impossible
                    # to reuse the object to log in again after
                    # logout. That's why we dereference it here,
                    # and get a fresh instance on connect.
                    self.imap = None
                self.logger.debug("ImapClient  disconnected")

    def all_messages_env(self) -> List[MessageEnvelopeData]:
        '''
        Provides iterable over collection of all envelopes fetched
        from server.
        '''
        self.refresh_if_needed()

        with self._local_lock:
            rv = self._envelope_cache.values()

        return rv

    def refresh_if_needed(self) -> int:
        '''
        A naive mailbox refresh. Calling it pings the server with NOOP
        and returns a "version" of mailbox observed. Version is just a
        counter incremented each time when mailbox change is detected.
        '''
        with self._local_lock:
            if (self._connected and time.time() > self._last_mailbox_query
               + ImapClient.QUERY_INTERVAL):
                with self._imap_lock:
                    self.logger.debug('querying IMAP server')
                    again = True
                    repeats = 3
                    while again:
                        try:
                            reply = self.imap.noop()
                            again = False
                        except (ConnectionResetError, imaplib.IMAP4.abort):
                            if repeats > 0:
                                repeats -= 1
                                self.logger.debug('connection lost, trying to reconnect')
                                self.connect()
                            else:
                                raise


                    self._last_mailbox_query = time.time()
                    if len(reply) > 1:
                        try:
                            self._invalidate_and_reread()
                        except Exception:
                            self.logger.error("exception when refereshing mailbox",
                                              exc_info=True)
                    else:
                        self.logger.warning('unknown response received: %s', reply)
            return  self._mailbox_version

    def get_message(self, msg_id) -> List[MessagePart]:
        '''
        Read and return single message (basic headers and
        main contents) as byte array.
        '''
        self.logger.debug('get_message called for: %d', msg_id)
        with self._local_lock:
            if msg_id not in self._message_cache:
                self._message_cache[msg_id] = self._load_msg(msg_id)
            rv = self._message_cache[msg_id]

        return rv

    def _load_msg(self, mid) -> List[MessagePart]:
        '''
        Load a message with given identifier from IMAP server and
        return it as a "pretty string".
        '''
        self.logger.debug('fetching message %d', mid)
        rv = list()
        with self._imap_lock:
            data = self.imap.fetch([mid], 'RFC822')
        parser = BytesParser(policy=policy.default)
        msg = parser.parsebytes(data[mid][b'RFC822'])
        subj = msg['Subject']
        subj = _decode_text(subj)

        body = msg.get_body(('html', 'plain'))
        if body:
            content = body.get_payload(decode=True)
            charset = body.get_content_charset()
        else:
            content = "This message contains no decodable body part."

        if not charset:
            charset = 'utf-8'
        content = content.decode(charset)
        content = bytes(content, charset)
        ctype = body.get_content_type()
        rv.append(MessagePart('main_body' +
                              mimetypes.guess_extension(ctype),
                              ctype, content))

        for att in msg.iter_attachments():
            content = att.get_payload(decode=True)
            charset = att.get_content_charset()
            if not charset:
                charset = 'utf-8'
            if content is str:
                content = bytes(content, 'utf-8')
            part = MessagePart(att.get_filename(),
                               att.get_content_type(),
                               content)
            rv.append(part)
        return rv

    def _del_msg(self, msg_id):
        '''
        remove message from local cache
        '''
        if msg_id in self._envelope_cache:
            del self._envelope_cache[msg_id]
            self._all_ids.remove(msg_id)

        if msg_id in self._message_cache:
            del self._message_cache[msg_id]


    def _prefetch_msg(self, msg_id):
        '''
        Fetch headers of given message and register them in
        cache.
        '''
        data = self.imap.fetch([msg_id], 'ENVELOPE')
        env = data[msg_id][b'ENVELOPE']
        self._register_envelope(msg_id, env)

    def _parse_address(self, addr) -> Set[str]:
        '''
        Parse address object tuple (as described in
        https://imapclient.readthedocs.io/en/2.1.0/api.html#imapclient.response_types.Address)
        and return a string suitable for usage as a path element.
        '''
        # pylint: disable=no-self-use

        rv = set()

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

    def _register_envelope(self, msgid, env):
        '''
        Create sender and timeline cache entries, based on
        raw envelope of received message.
        '''

        senders = set()
        for addr in [env.sender, env.from_]:
            senders |= self._parse_address(addr)

        sub = decode_header(env.subject.decode())
        subject = _decode_text(sub)

        recipients = set()
        for addr in [env.to, env.cc, env.bcc]:
            recipients |= self._parse_address(addr)

        hdr = MessageEnvelopeData(msgid, list(senders), list(recipients),
                                  subject, env.date)
        self._envelope_cache[msgid] = hdr
        self._all_ids.add(msgid)


    def _invalidate_and_reread(self):
        '''
        invalidate local message list. Reread and update index.
        '''
        srv_msg_ids = self.imap.search('ALL')
        ids_to_remove = self._all_ids - set(srv_msg_ids)
        ids_to_add = set(srv_msg_ids) - self._all_ids
        self.logger.debug('invalidate_and_reread ids_to_remove=%s ids_to_add=%s',
                          str(ids_to_remove), str(ids_to_add))
        for mid in ids_to_remove:
            self.logger.debug('removing from cache message %d', mid)
            self._del_msg(mid)

        for mid in ids_to_add:
            self.logger.debug('adding to cache message %d', mid)
            self._prefetch_msg(mid)

        if len(ids_to_remove) + len(ids_to_add) > 0:
            self._mailbox_version += 1



def _decode_text(sub) -> str:
    if isinstance(sub, str):
        rv = sub
    else:
        rv = ''
        for (subject, charset) in sub:
            if isinstance(subject, str):
                rv += subject
            else:
                if not charset:
                    charset = 'utf-8'
                rv += subject.decode(charset)
    return rv
