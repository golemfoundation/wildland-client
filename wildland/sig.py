
import tempfile

import gnupg


# TODO move to exc?
class SigError(Exception):
    pass


class SigContext:
    '''
    A class for signing and verifying signatures. Operates on 'signer'
    identifiers.
    '''

    def sign(self, data: bytes, signer: str) -> bytes:
        raise NotImplementedError()

    def verify(self, signer: str, signature: str, data: bytes):
        raise NotImplementedError()


class DummySigContext(SigContext):
    '''
    A SigContext that does not require a valid signature, for testing purposes.
    '''
    def sign(self, data: bytes, signer: str) -> bytes:
        raise NotImplementedError()

    def verify(self, signer: str, signature: str, data: bytes):
        pass



class GpgSigContext:
    '''
    GnuPG wrapper, using python-gnupg library:

    https://gnupg.readthedocs.io/en/latest/

    Uses keys stored in GnuPG keyring. The signer -> fingerprint association
    must be first registered using add_signer().
    '''

    def __init__(self, gnupghome=None):
        self.gpg = gnupg.GPG(gnupghome=gnupghome)
        self.signers = {}

    def add_signer(self, signer: str, keyid: str):
        self.signers[signer] = keyid

    def gen_test_key(self, passphrase: str = None) -> str:
        '''
        Generate a new key for testing purposes.
        '''

        input_data = self.gpg.gen_key_input(
            name_real='Wildland Test',
            key_length=1024,
            subkey_length=1024,
            passphrase=passphrase)
        key = self.gpg.gen_key(input_data)
        if not key:
            raise Exception('gen_key failed')
        return key.fingerprint

    def verify(self, signer: str, signature: str, data: bytes):
        if signer not in self.signers:
            raise SigError('Unknown signer: {!r}'.format(signer))

        fingerprint = self.signers[signer]

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

        if verified.fingerprint != fingerprint:
            raise SigError('Wrong key for signature ({}, expected {})'.format(
                           verified.fingerprint, fingerprint))

    def sign(self, signer: str, data: bytes, passphrase: str = None) -> bytes:
        if signer not in self.signers:
            raise SigError('Unknown signer: {!r}'.format(signer))

        fingerprint = self.signers[signer]
        signature = self.gpg.sign(data, keyid=fingerprint, detach=True,
                                  passphrase=passphrase)
        if not signature:
            raise Exception('sign failed')
        return str(signature)
