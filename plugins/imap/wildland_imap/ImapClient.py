'''
ImapClient is a module delivering an IMAP mailbox representation
for wildland imap backend. The representation is read-only,
update-sensitive and includes primitive caching support.
'''

import logging
import time

from dataclasses import dataclass
from threading import Thread, Lock
from email.header import decode_header
from email.parser import BytesParser
from email import policy
from datetime import datetime
from imapclient import IMAPClient
from .TimelineDate import TimelineDate, DatePart

@dataclass
class MessageHeader:
    '''
    Compact representation of e-mail header, as we use it
    for processing internally.
    '''
    sender: str
    subject: str
    recv_t: datetime

class ImapClient:
    '''
    IMAP protocol client implementation adding some additional
    level of abstraction over generic IMAPClient to expose
    the features needed by the wildland filesystem.
    '''

    def __init__(self, host: str, login: str, password: str,
                 folder: str):
        self.logger = logging.getLogger('ImapClient')
        self.logger.debug('creating IMAP client for host: %s', host)
        self.imap = IMAPClient(host, use_uid=True)
        self.login = login
        self.password = password
        self.folder = folder
        # sender is a dictionary where key is sender e-mail and
        # value is a list of (message id, message header) tuples.
        self._senders = dict()

        # timeline is a tree implemented using dictionaries. Key
        # on every level is of TimelineDate type set to relevant
        # accuracy (i.e. year on fist level, month on second...).
        self._timeline = dict()

        # message id: message contents (only populated, when
        # messge content is requested)
        self._message_cache = dict()

        # all ids retrieved
        self._all_ids = list()

        # lock guarding access to local data structures
        self._local_lock = Lock()

        # monitor thread monitors changes to the inbox and
        # updates the cache accordingly
        self._monitor_thread = None
        self._connected = False

        # lock guarding access to imap client
        self._imap_lock = Lock()


    def connect(self):
        '''
        Connect to IMAP server and start periodic monitoring task.
        '''
        self.logger.debug('connecting to IMAP server')
        self.imap.login(self.login, self.password)
        self.imap.select_folder(self.folder)
        self._senders = dict()
        self._timeline = dict()
        self._message_cache = dict()
        self._all_ids = list()

        self._connected = True
        self._monitor_thread = Thread(target=self._monitor_main)
        self._monitor_thread.start()

    def disconnect(self):
        '''
        disconnect from IMAP server.
        '''
        self.logger.debug('disconnecting from IMAP server')
        self._connected = False
        self._monitor_thread.join()
        self._monitor_thread = None
        with self._imap_lock:
            self.imap.logout()

    def all_senders(self):
        '''
        return list of all sender emails currently received from server.
        '''
        self._load_messages_if_needed()
        with self._local_lock:
            rv = self._senders.keys()
        return rv

    def sender_messages(self, sender_email):
        '''
        Return list of messages of single sender.
        '''
        self._load_messages_if_needed()
        with self._local_lock:
            self.logger.debug('sender %s{sender_email} has %d  messages',
                          sender_email, self._senders[sender_email])
            rv = self._senders[sender_email]
        return rv

    def get_message(self, msg_id) -> bytes:
        '''
        Read and return single message (basic headers and
        main contents) as byte array.
        '''
        with self._local_lock:
            if msg_id not in self._message_cache:
                self._message_cache[msg_id] = self._load_msg(msg_id).encode('utf-8')
            rv = self._message_cache[msg_id]

        return rv

    def timeline_children(self, parent: TimelineDate):
        '''
        generates list of direct childern entries
        for given date constraint.
        '''
        self._load_messages_if_needed()
        with self._local_lock:
            rv = self._resolve_timeline(parent).keys()
        return rv

    def mails_at_date(self, day: TimelineDate):
        '''
        generates list of emails received at given date.
        '''
        with self._local_lock:
            rv = self._resolve_timeline(day)
        return rv


    def _resolve_timeline(self, parent: TimelineDate):
        base = DatePart.EPOCH
        rv = self._timeline[parent.up_to(base)]

        while base < parent.accuracy:
            base = base.advance()
            rv = rv[parent.up_to(base)]

        return rv


    def _load_messages_if_needed(self):
        '''
        Load message headers if needed to populate the cache.
        Current implementation doesn't allow for incremental
        cache updates, so every time the cache is being refreshed
        the whole message list is being retrieved. This is
        likely something to be addressed in future.
        '''

        self.logger.debug('entering _load_messages_if_needed')
        with self._local_lock:
            if self._senders:
                self.logger.debug('fast-leaving _load_messages_if_needed')
                return

        with self._imap_lock, self._local_lock:
            msg_ids = self.imap.search('ALL')
            self._all_ids = msg_ids
            for msgid, data in self.imap.fetch(msg_ids,
                                               ['ENVELOPE']).items():
                env = data[b'ENVELOPE']
                self._register_envelope(msgid, env)
        self.logger.debug('leaving _load_messages_if_needed')

    def _load_msg(self, mid) -> str:
        '''
        Load a message with given identifier from IMAP server and
        return it as a "pretty string".
        '''
        self.logger.debug('fetching message %d', mid)
        with self._imap_lock:
            data = self.imap.fetch([mid], 'RFC822')
        parser = BytesParser(policy=policy.default)
        msg = parser.parsebytes(data[mid][b'RFC822'])
        sender = msg['From']
        subj = msg['Subject']
        subj = _decode_subject(subj)

        recv = msg['Date']

        body = msg.get_body(('plain', 'related', 'html'))
        content = body.get_payload(decode=True)
        charset = body.get_content_charset()
        if not charset:
            charset = 'utf-8'
        content = content.decode(charset)

        return 'From: %s\nReceived: %s\nSubject: %s\n\n%s' % \
            (sender, recv, subj, content)

    def _del_msg(self, msg_id):
        '''
        remove message from local cache
        '''
        hdr = None
        for lst in self._senders.values():
            for an_id, a_hdr in lst:
                if an_id == msg_id:
                    hdr = a_hdr
                    lst.remove((an_id, a_hdr))
                    break
            if hdr is not None:
                break
        if hdr is not None:
            if msg_id in self._message_cache:
                del self._message_cache[msg_id]
            rd = TimelineDate(DatePart.DAY, hdr.recv_t)
            self._timeline[rd.up_to(DatePart.EPOCH)] \
                [rd.up_to(DatePart.YEAR)] \
                [rd.up_to(DatePart.MONTH)] \
                [rd.up_to(DatePart.DAY)].remove((msg_id, hdr))
            self._all_ids.remove(msg_id)

    def _prefetch_msg(self, msg_id):
        '''
        Fetch headers of given message and register them in
        cache.
        '''
        data = self.imap.fetch([msg_id], 'ENVELOPE')
        self.logger.debug('for msg %d received env %s', msg_id, data)
        env = data[msg_id][b'ENVELOPE']
        self._register_envelope(msg_id, env)

    def _register_envelope(self, msgid, env):
        '''
        Create sender and timeline cache entries, based on
        raw envelope of received message.
        '''
        sender = f'{env.sender[0].mailbox.decode()}@{env.sender[0].host.decode()}'
        sub = decode_header(env.subject.decode())
        subject = _decode_subject(sub)

        hdr = MessageHeader(sender=sender, subject=subject,
                            recv_t=env.date)

        self._all_ids.append(msgid)
        if sender not in self._senders:
            self._senders[sender] = [(msgid, hdr)]
        else:
            self._senders[sender].append((msgid, hdr))
        self.logger.debug('message %d added to sender %s', msgid, sender)

        self._register_in_timeline(self._timeline,
                                   DatePart.EPOCH, (msgid, hdr))

    def _register_in_timeline(self, tdata: dict, level: DatePart,
                              what: (int, MessageHeader)):
        '''
        Create a timeline entry for message header. The parameter
        meaning is as follows:
        - tdata is a "top-level" dictionary, holding the entries
          AT278 given time 'level'
        - 'level' is the level we are currently working at
        - 'date' is a receive date of a message
        - 'what' is message id and header which we ultimately need
          to store
        '''
        date = TimelineDate(level, what[1].recv_t)
        if level == DatePart.DAY:
            # We are at "leaf" so just store the message and
            # one.
            if date in tdata:
                tdata[date].append(what)
            else:
                tdata[date] = [what]
            self.logger.debug('message %d added in timeline %s', what[0],
                              date)
        else:
            if date not in tdata:
                tdata[date] = dict()
            self._register_in_timeline(tdata[date],
                                       level.advance(),
                                       what)

    def _invalidate_and_reread(self):
        '''
        ivalidate local message list. Reread and update index.
        '''
        with self._local_lock:
            srv_msg_ids = self.imap.search('ALL')
            ids_to_remove = set(self._all_ids) - set(srv_msg_ids)
            ids_to_add = set(srv_msg_ids) - set(self._all_ids)
            self.logger.debug('invalidate_and_reread ids_to_remove=%s ids_to_add=%s',
                              ids_to_remove, ids_to_add)
            for mid in ids_to_remove:
                self.logger.debug('removing from cache message %d', mid)
                self._del_msg(mid)

            for mid in ids_to_add:
                self.logger.debug('adding to cache message %d',
                                  mid)
                self._prefetch_msg(mid)

    def _monitor_main(self):
        while self._connected:
            with self._imap_lock:
                reply = self.imap.noop()
                if len(reply) > 1:
                    try:
                        self._invalidate_and_reread()
                    except Exception:
                        self.logger.error("exception in monitor thread",
                                          exc_info=True)
                else:
                    self.logger.warning('unknown response received: %s', reply)
            time.sleep(10)

def _decode_subject(sub) -> str:
    if isinstance(sub, str):
        rv = sub
    else:
        subject = sub[0][0]
        charset = sub[0][1]
        if isinstance(subject, str):
            rv = subject
        else:
            if not charset:
                charset = 'utf-8'
            rv = subject.decode(charset)
    return rv
