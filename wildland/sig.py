'''
Module for handling signatures. Currently provides two backends: GPG, and a
"dummy" one.
'''

import tempfile

import gnupg

from .exc import WildlandError


class SigError(WildlandError):
    '''
    Exception class for problems during the signing or verification process.
    '''


class SigContext:
    '''
    A class for signing and verifying signatures. Operates on 'signer'
    identifiers, serving as key fingerprints.
    '''

    def __init__(self):
        self.signers = set()

    def add_signer(self, signer: str):
        '''
        Add a signer to recognized signers.
        '''
        self.signers.add(signer)

    def find(self, key_id: str) -> str:
        '''
        Find a canonical form for the key.
        '''
        raise NotImplementedError()

    def sign(self, signer: str, data: bytes) -> str:
        '''
        Sign data using a given signer's key.
        '''
        raise NotImplementedError()

    def verify(self, signer: str, signature: str, data: bytes,
               self_signed=False):
        '''
        Verify signature for data.
        If self_signed, ignore that a signer is not recognized.
        '''
        raise NotImplementedError()


class DummySigContext(SigContext):
    '''
    A SigContext that requires a dummy signature (of the form "dummy.{signer}"),
    for testing purposes.
    '''

    def find(self, key_id: str) -> str:
        return key_id

    def sign(self, signer: str, data: bytes) -> str:
        return f'dummy.{signer}'

    def verify(self, signer: str, signature: str, data: bytes,
               self_signed=False):
        expected_signature = f'dummy.{signer}'
        if signature != expected_signature:
            raise SigError(
                'Expected {!r}, got {!r}'.format(
                    expected_signature, signature))


class GpgSigContext(SigContext):
    '''
    GnuPG wrapper, using python-gnupg library:

    https://gnupg.readthedocs.io/en/latest/

    Uses keys stored in GnuPG keyring. The fingerprint association
    must be first registered using add_signer().
    '''

    def __init__(self, gnupghome=None):
        super().__init__()
        self.gnupghome = gnupghome
        self.gpg = gnupg.GPG(gnupghome=gnupghome)

    @staticmethod
    def convert_fingerprint(fingerprint):
        '''
        Convert GPG fingerprint to an unambiguous '0xcoffee' format.
        '''
        fingerprint = fingerprint.lower()
        if not fingerprint.startswith('0x'):
            fingerprint = '0x' + fingerprint
        return fingerprint

    def find(self, key_id: str) -> str:
        keys = [self.convert_fingerprint(k['fingerprint'])
                for k in self.gpg.list_keys(keys=key_id)]
        if len(keys) > 1:
            raise SigError('Multiple keys found for {}: {}'.format(
                key_id, keys))
        if len(keys) == 0:
            raise SigError('No key found for {}'.format(key_id))
        return keys[0]

    def gen_test_key(self, name, passphrase: str = None) -> str:
        '''
        Generate a new key for testing purposes.
        '''

        input_data = self.gpg.gen_key_input(
            name_real=name,
            key_length=1024,
            subkey_length=1024,
            passphrase=passphrase)
        key = self.gpg.gen_key(input_data)
        if not key:
            raise Exception('gen_key failed')
        return self.convert_fingerprint(key.fingerprint)

    def verify(self, signer: str, signature: str, data: bytes,
               self_signed=False):
        if not self_signed and signer not in self.signers:
            raise SigError('Unknown signer: {!r}'.format(signer))

        # Create a file for detached signature, because gnupg needs to get it
        # from file. NamedTemporaryFile() creates the file as 0o600, so no need
        # to set umask.
        with tempfile.NamedTemporaryFile(mode='w', prefix='wlsig.') as sig_file:
            sig_file.write(signature)
            sig_file.flush()

            verified = self.gpg.verify_data(
                sig_file.name, data)

        if not data:
            raise Exception('verify failed')

        if not verified.valid:
            raise SigError('Could not verify signature')

        if self.convert_fingerprint(verified.fingerprint) != signer:
            raise SigError('Wrong key for signature ({}, expected {})'.format(
                           verified.fingerprint, signer))

    def sign(self, signer: str, data: bytes, passphrase: str = None) -> str:
        # pylint: disable=arguments-differ

        if signer not in self.signers:
            raise SigError('Unknown signer: {!r}'.format(signer))

        signature = self.gpg.sign(data, keyid=signer, detach=True,
                                  passphrase=passphrase)
        if not signature:
            raise Exception('sign failed')
        return str(signature)
