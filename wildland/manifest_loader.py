'''
Manifest handling according to user configuration.
'''

from pathlib import Path
import os
from typing import Optional

from .schema import Schema
from .sig import DummySigContext, GpgSigContext
from .manifest import Manifest
from .user import User
from .exc import WildlandError

DEFAULT_BASE_DIR = '.wildland'


class ManifestLoader:
    '''
    Common class for manifest handling (loading, verification etc.) according
    to user configuration.
    '''

    def __init__(self, *, dummy=False, base_dir=None, gpg_home=None):
        if base_dir is None:
            home_dir = os.getenv('HOME')
            assert home_dir
            self.base_dir = Path(home_dir) / DEFAULT_BASE_DIR
        else:
            self.base_dir = Path(base_dir)

        self.user_dir = self.base_dir / 'users'
        self.storage_dir = self.base_dir / 'storage'

        if dummy:
            self.sig = DummySigContext()
        else:
            self.sig = GpgSigContext(gpg_home)

        self.users = []

    def load_users(self):
        '''
        Load recognized users from default directory.
        '''

        if not os.path.exists(self.user_dir):
            return
        for name in sorted(os.listdir(self.user_dir)):
            path = self.user_dir / name
            self.load_user(path)

    def load_user(self, path) -> User:
        '''
        Load a user from YAML path.
        '''

        manifest = Manifest.from_file(path, self.sig, User.SCHEMA,
                                      self_signed=True)
        user = User(manifest, path)

        self.users.append(user)
        self.sig.add_signer(user.pubkey)
        return user

    def find_user(self, name) -> User:
        '''
        CLI helper: find (and load) user by name.
        '''
        path = self.find_manifest(name, 'user')
        return self.load_user(path)

    def find_manifest(self, name, manifest_type=None) -> Path:
        '''
        CLI helper: find manifest by name.
        '''

        if not name.endswith('.yaml') and manifest_type is not None:
            if manifest_type == 'user':
                path = self.user_dir / f'{name}.yaml'
            elif manifest_type == 'storage':
                path = self.storage_dir / f'{name}.yaml'
            else:
                assert False, manifest_type
            if os.path.exists(path):
                return path

        if os.path.exists(name):
            return Path(name)

        raise WildlandError(f'File not found: {name}')

    @classmethod
    def validate_manifest(cls, manifest, manifest_type=None):
        '''
        Validate a (possibly unsigned) manifest by type.
        '''

        if manifest_type == 'user':
            manifest.apply_schema(User.SCHEMA)
        elif manifest_type == 'storage':
            manifest.apply_schema(Schema('storage'))
            manifest.apply_schema(Schema('storage-{}'.format(
                manifest._fields['type'])))
        else:
            assert False, manifest_type

    def create_user(self, pubkey, name=None) -> Path:
        '''
        Create a new user.
        '''

        self.sig.add_signer(pubkey)

        manifest = Manifest.from_fields({
            'signer': pubkey,
            'pubkey': pubkey,
        })
        manifest.sign(self.sig)
        manifest_data = manifest.to_bytes()
        if name is None:
            name = pubkey
        if not os.path.exists(self.user_dir):
            os.makedirs(self.user_dir)
        path = self.user_dir / f'{name}.yaml'
        with open(path, 'wb') as f:
            f.write(manifest_data)
        return path

    def create_storage(self, pubkey, storage_type, fields, name=None) -> Path:
        '''
        Create a new storage.
        '''
        manifest = Manifest.from_fields({
            'signer': pubkey,
            'type': storage_type,
            **fields
        })
        schema = Schema(f'storage-{storage_type}')
        manifest.apply_schema(schema)
        manifest.sign(self.sig)
        manifest_data = manifest.to_bytes()
        if not os.path.exists(self.storage_dir):
            os.makedirs(self.storage_dir)
        path = self.storage_dir / f'{name}.yaml'
        with open(path, 'wb') as f:
            f.write(manifest_data)
        return path

    def parse_manifest(self, data: bytes,
                       schema: Optional[Schema] = None) -> Manifest:
        '''
        Parse a user manifest, verifying it.
        '''
        return Manifest.from_bytes(data, self.sig, schema)
