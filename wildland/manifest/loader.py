# Wildland Project
#
# Copyright (C) 2020 Golem Foundation,
#                    Paweł Marczewski <pawel@invisiblethingslab.com>,
#                    Wojtek Porczyk <woju@invisiblethingslab.com>
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

'''
Manifest handling according to user configuration.
'''

from pathlib import Path
import os
from typing import Optional, Dict, Any, List, Tuple
import uuid
import warnings
import logging

import yaml

from ..user import User

from .schema import Schema, SchemaError
from .sig import SigContext, DummySigContext, GpgSigContext
from .manifest import Manifest
from .manifest import ManifestError
from ..exc import WildlandError


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

        self.sig: SigContext
        if self.config.get('dummy'):
            self.sig = DummySigContext()
        else:
            self.sig = GpgSigContext(self.config.get('gpg_home'))

        self.users = []
        self.closed = False

    def close(self):
        '''
        Clean up.
        '''
        self.sig.close()
        self.closed = True

    def __del__(self):
        if not self.closed:
            warnings.warn('ManifestLoader: not closed', ResourceWarning)
            self.close()

    def load_users(self):
        '''
        Load recognized users from default directory.
        '''

        if not os.path.exists(self.user_dir):
            return
        for name in sorted(os.listdir(self.user_dir)):
            path = self.user_dir / name
            try:
                self.load_user(path)
            except WildlandError as e:
                logging.warning('error loading user manifest: %s: %s',
                               path, e)

    def load_user(self, path) -> User:
        '''
        Load a user from YAML path.
        '''

        manifest = Manifest.from_file(path, self.sig, User.SCHEMA,
                                      self_signed=Manifest.REQUIRE)
        user = User(manifest, path)

        self.users.append(user)
        self.sig.add_pubkey(user.pubkey)
        return user

    def find_user(self, name) -> User:
        '''
        CLI helper: find (and load) user by name.
        '''

        path, data = self.read_manifest(name, 'user')
        manifest = Manifest.from_bytes(data, self.sig, User.SCHEMA,
                                       self_signed=Manifest.REQUIRE)
        user = User(manifest, path)

        self.users.append(user)
        self.sig.add_pubkey(user.pubkey)
        return user

    def find_default_user(self) -> Optional[User]:
        '''
        Find and load the default configured user (if any).
        '''

        signer = self.config.get('default_user')
        for user in self.users:
            if user.signer == signer:
                return user
        return None

    def read_manifest(self, name, manifest_type=None, *, remote=False) \
        -> Tuple[Optional[Path], bytes]:
        '''
        CLI helper: find manifest by description and read it.

        The name can be:
        - a local path (ending with '.yaml')
        - short name, in which case it's loaded from the appropriate manifest
        directory
        - Wildland path (such as :/foo/bar)

        If 'remote' is true, also traverse the Wildland path further. In this
        case, the method might read a manifest that is not available locally.

        Note that in case of Wildland path, we will also verify the manifest
        during loading, so loading malformed manifest is not possible.
        '''

        # TODO: This is circular dependency with resolve.py, refactor
        # pylint: disable=import-outside-toplevel, cyclic-import
        from ..resolve import WildlandPath, Search

        # TODO: Possibly return WildlandPath
        # TODO: Return the context with appropriate signing keys imported

        # Wildland path
        if WildlandPath.match(name):
            if manifest_type not in ['container']:
                raise ManifestError('Wildland paths are supported for containers only')

            wlpath = WildlandPath.from_str(name)
            search = Search(self, wlpath)
            container, manifest_path = search.read_container(remote=remote)
            return manifest_path, container.manifest.to_bytes()

        # Short name
        if not name.endswith('.yaml') and manifest_type is not None:
            path = self.manifest_dir(manifest_type) / f'{name}.yaml'
            if os.path.exists(path):
                return path, path.read_bytes()

        # Local path
        if os.path.exists(name):
            path = Path(name)
            return path, path.read_bytes()

        raise ManifestError(f'Manifest not found: {name}')

    def load_manifest(self, name, manifest_type=None, *, remote=False) \
        -> Tuple[Optional[Path], Manifest]:
        '''
        CLI helper: find manifest by name, and load it.
        '''

        path, data = self.read_manifest(name, manifest_type, remote=remote)
        manifest = Manifest.from_bytes(data, self.sig)
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

        self_signed = manifest_type == 'user'

        path = self.manifest_dir(manifest_type)
        if not os.path.exists(path):
            return []
        manifests = []
        for file_name in sorted(os.listdir(path)):
            if file_name.endswith('.yaml'):
                manifest_path = path / file_name
                manifest = Manifest.from_file(manifest_path, self.sig,
                                              self_signed=self_signed)
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

    def make_name(self, base_name: str, manifest_type) -> str:
        '''
        Make up an unused name for a new manifest.
        In case of collisions, tries '{name}', '{name}.1', etc.
        '''

        i = 0
        while True:
            suffix = '' if i == 0 else f'.{i}'
            if not os.path.exists(
                    self.manifest_dir(manifest_type) /
                    (base_name + suffix + '.yaml')):
                return base_name + suffix
            i += 1

    def create_user(self, signer, pubkey, paths, name) -> Path:
        '''
        Create a new user.
        '''

        manifest = Manifest.from_fields({
            'signer': signer,
            'paths': paths,
            'containers': []
        })

        with self.sig.copy() as sig_temp:
            sig_temp.add_pubkey(pubkey)
            manifest.sign(sig_temp, attach_pubkey=True)

        if name is None:
            name = self.make_name(signer, 'user')

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

    def create_storage(self, signer, storage_type, fields, name) -> Path:
        '''
        Create a new storage.
        '''

        manifest = Manifest.from_fields({
            'signer': signer,
            'type': storage_type,
            **fields
        })
        schema = Schema(f'storage-{storage_type}')
        manifest.apply_schema(schema)
        manifest.sign(self.sig)

        if name is None:
            container_path = fields['container_path']
            base_name = Path(container_path).name
            name = self.make_name(base_name, 'storage')

        return self.save_manifest(manifest, name, 'storage')

    def create_container(self,
                         signer: str,
                         paths: List[str],
                         name: Optional[str]) -> Path:
        '''
        Create a new container.

        If the list of paths doesn't contain UUID (/.uuid/...), the function
        will add one at the beginning.
        '''

        for path in paths:
            if path.startswith('/.uuid/'):
                ident = path[len('/.uuid/'):]
                break
        else:
            ident = str(uuid.uuid4())
            paths = [f'/.uuid/{ident}', *paths]

        if name is None:
            name = self.make_name(ident, 'container')

        manifest = Manifest.from_fields({
            'signer': signer,
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
    Wildland configuration, by default loaded from ~/.config/wildland/config.yaml.

    Consists of three layers:
    - default_fields (set here)
    - file_fields (loaded from file)
    - override_fields (provided from command line)
    '''

    filename = 'config.yaml'

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

        home_dir_s = os.getenv('HOME')
        assert home_dir_s
        home_dir = Path(home_dir_s)

        if base_dir is None:
            xdg_home = os.getenv('XDG_CONFIG_HOME')
            if xdg_home:
                base_dir = Path(xdg_home) / 'wildland'
            else:
                base_dir = Path(home_dir) / '.config/wildland'
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
