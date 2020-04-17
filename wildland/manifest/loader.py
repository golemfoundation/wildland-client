'''
Manifest handling according to user configuration.
'''

from pathlib import Path
import os
from typing import Optional, Dict, Any, List, Tuple
import uuid

import yaml

from .schema import Schema, SchemaError
from .sig import DummySigContext, GpgSigContext
from .manifest import Manifest
from .user import User
from .manifest import ManifestError


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
        self.container_dir = Path(self.config.get('container_dir'))

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

        pubkey = self.config.get('default_user')
        for user in self.users:
            if user.pubkey == pubkey:
                return user
        return None

    def find_manifest(self, name, manifest_type=None) -> Optional[Path]:
        '''
        CLI helper: find manifest by name.
        '''

        if not name.endswith('.yaml') and manifest_type is not None:
            path = self.manifest_dir(manifest_type) / f'{name}.yaml'
            if os.path.exists(path):
                return path

        if os.path.exists(name):
            return Path(name)

        return None

    def load_manifest(self, name, manifest_type=None) \
        -> Tuple[Optional[Path], Optional[Manifest]]:
        '''
        CLI helper: find manifest by name, and load it.
        '''

        path = self.find_manifest(name, manifest_type)
        if not path:
            return None, None
        manifest = Manifest.from_file(path, self.sig)
        self.validate_manifest(manifest, manifest_type)
        return (path, manifest)

    def manifest_dir(self, manifest_type) -> Path:
        '''
        Return default path for a given manifest type.
        '''

        if manifest_type == 'user':
            return self.user_dir
        if manifest_type == 'storage':
            return self.storage_dir
        if manifest_type == 'container':
            return self.container_dir
        assert False, manifest_type
        return None

    def load_manifests(self, manifest_type) -> List[Tuple[Path, Manifest]]:
        '''
        Load all manifests for a given type. Returns list of tuples
        (path, manifest).
        '''

        path = self.manifest_dir(manifest_type)
        if not os.path.exists(path):
            return []
        manifests = []
        for file_name in sorted(os.listdir(path)):
            if file_name.endswith('.yaml'):
                manifest_path = path / file_name
                manifest = Manifest.from_file(manifest_path, self.sig)
                try:
                    self.validate_manifest(manifest, manifest_type)
                except SchemaError as e:
                    raise ManifestError(
                        f'Error validating {manifest_path}: {e}')
                manifests.append((manifest_path, manifest))

        return manifests

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
        elif manifest_type == 'container':
            manifest.apply_schema(Schema('container'))
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
        if name is None:
            name = pubkey

        return self.save_manifest(manifest, name, 'user')

    def save_manifest(self, manifest, name, manifest_type):
        '''
        Save a manifest to a default path.
        '''

        manifest_data = manifest.to_bytes()
        manifest_dir = self.manifest_dir(manifest_type)
        if not os.path.exists(manifest_dir):
            os.makedirs(manifest_dir)
        path = manifest_dir / f'{name}.yaml'
        if os.path.exists(path):
            raise ManifestError(f'File already exists: {path}')
        with open(path, 'wb') as f:
            f.write(manifest_data)
        return path

    def create_storage(self, pubkey, storage_type, fields, name) -> Path:
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
        return self.save_manifest(manifest, name, 'storage')

    def create_container(self,
                         pubkey: str,
                         paths: List[str],
                         name: str) -> Path:
        '''
        Create a new container.

        If the list of paths doesn't contain UUID (/.uuid/...), the function
        will add one at the beginning.
        '''

        if not any(path.startswith('/.uuid/') for path in paths):
            ident = str(uuid.uuid4())
            paths = [f'/.uuid/{ident}'] + paths

        manifest = Manifest.from_fields({
            'signer': pubkey,
            'paths': paths,
            'backends': {'storage': []},
        })
        schema = Schema('container')
        manifest.apply_schema(schema)
        manifest.sign(self.sig)
        return self.save_manifest(manifest, name, 'container')

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
                 base_dir,
                 path: Path,
                 default_fields: Dict[str, Any],
                 file_fields: Dict[str, Any]):
        self.base_dir = base_dir
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

    def override(self, *, dummy=False, uid=None, gid=None):
        '''
        Override configuration based on command line arguments.
        '''
        if dummy:
            self.override_fields['dummy'] = True
        if uid is not None:
            self.override_fields['uid'] = uid
        if uid is not None:
            self.override_fields['gid'] = gid

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
                if not file_fields:
                    file_fields = {}
        else:
            file_fields = {}
        return cls(base_dir, path, default_fields, file_fields)

    @classmethod
    def get_default_fields(cls, home_dir, base_dir) -> dict:
        '''
        Compute the default values for all the unspecified fields.
        '''

        return {
            'user_dir': base_dir / 'users',
            'storage_dir': base_dir / 'storage',
            'container_dir': base_dir / 'containers',
            'mount_dir': home_dir / 'wildland',
            'dummy': False,
            'gpg_home': None,
            'default_user': None,
            'uid': os.getuid(),
            'gid': os.getgid(),
        }
