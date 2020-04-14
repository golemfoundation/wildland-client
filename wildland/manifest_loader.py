'''
Manifest handling according to user configuration.
'''

from pathlib import Path
import os
from typing import Optional, Dict, Any
import yaml

from .schema import Schema
from .sig import DummySigContext, GpgSigContext
from .manifest import Manifest
from .user import User


class ManifestLoader:
    '''
    Common class for manifest handling (loading, verification etc.) according
    to user configuration.
    '''

    def __init__(self, base_dir=None, **config_kwargs):
        self.config = Config.load(base_dir)
        self.config.override(**config_kwargs)

        self.user_dir = Path(self.config.get('user_dir'))
        self.storage_dir = Path(self.config.get('storage_dir'))

        if self.config.get('dummy'):
            self.sig = DummySigContext()
        else:
            self.sig = GpgSigContext(self.config.get('gpg_home'))

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

    def find_user(self, name) -> Optional[User]:
        '''
        CLI helper: find (and load) user by name.
        '''

        path = self.find_manifest(name, 'user')
        if not path:
            return None
        return self.load_user(path)

    def find_default_user(self) -> Optional[User]:
        '''
        Find and load the default configured user (if any).
        '''

        name = self.config.get('default_user')
        if not name:
            return None
        return self.find_user(name)

    def find_manifest(self, name, manifest_type=None) -> Optional[Path]:
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

        return None

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


class Config:
    '''
    Wildland configuration, by default loaded from ~/.wildland/config.yaml.

    Consists of three layers:
    - default_fields (set here)
    - file_fields (loaded from file)
    - override_fields (provided from command line)
    '''

    filename = 'config.yaml'
    default_base_dir = '.wildland'

    def __init__(self,
                 path: Path,
                 default_fields: Dict[str, Any],
                 file_fields: Dict[str, Any]):
        self.path = path
        self.default_fields = default_fields
        self.file_fields = file_fields
        self.override_fields: Dict[str, Any] = {}

    def get(self, name: str):
        '''
        Get a configuration value for given name. The name has to be known,
        i.e. exist in defaults.
        '''

        assert name in self.default_fields, f'unknown config name: {name}'

        if name in self.override_fields:
            return self.override_fields[name]
        if name in self.file_fields:
            return self.file_fields[name]
        return self.default_fields[name]

    def override(self, *, gpg_home=None, dummy=False):
        '''
        Override configuration based on command line arguments.
        '''
        if gpg_home:
            self.override_fields['gpg_home'] = gpg_home
        if dummy:
            self.override_fields['dummy'] = True

    def update_and_save(self, **kwargs):
        '''
        Set new values and save to a file.
        '''

        self.file_fields.update(kwargs)
        with open(self.path, 'w') as f:
            yaml.dump(self.file_fields, f)

    @classmethod
    def load(cls, base_dir=None):
        '''
        Load a configuration file from base directory, if it exists; use
        defaults if not.
        '''

        home_dir = os.getenv('HOME')
        assert home_dir
        home_dir = Path(home_dir)

        if base_dir is None:
            base_dir = home_dir / cls.default_base_dir
        else:
            base_dir = Path(base_dir)

        default_fields = cls.get_default_fields(home_dir, base_dir)

        path = base_dir / cls.filename
        if os.path.exists(path):
            with open(path, 'r') as f:
                file_fields = yaml.safe_load(f)
        else:
            file_fields = {}
        return cls(path, default_fields, file_fields)

    @classmethod
    def get_default_fields(cls, home_dir, base_dir) -> dict:
        '''
        Compute the default values for all the unspecified fields.
        '''

        return {
            'user_dir': base_dir / 'users',
            'storage_dir': base_dir / 'storage',
            'mount_dir': home_dir / 'wildland',
            'dummy': False,
            'gpg_home': None,
            'default_user': None,
        }
