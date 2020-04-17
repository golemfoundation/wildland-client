'''
User manifest and user management
'''

from .manifest import Manifest
from .schema import Schema


class User:
    '''Wildland user'''

    SCHEMA = Schema('user')

    def __init__(self, manifest: Manifest, manifest_path=None):
        self.manifest = manifest
        self.manifest_path = manifest_path
        self.pubkey = manifest.fields['pubkey']
