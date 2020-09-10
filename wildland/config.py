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
Configuration file handling.
'''


from pathlib import Path
from typing import Dict, Any
import os
import types

import yaml

from .manifest.schema import Schema, SchemaError
from .exc import WildlandError


class Config:
    '''
    Wildland configuration, by default loaded from ~/.config/wildland/config.yaml.

    Consists of three layers:
    - default_fields (set here)
    - file_fields (loaded from file)
    - override_fields (provided from command line)
    '''

    schema = Schema('config')
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

    def override(self, *, dummy=False):
        '''
        Override configuration based on command line arguments.
        '''
        if dummy:
            self.override_fields['dummy'] = True

    def update_and_save(self, values: Dict[str, Any]):
        '''
        Set new values and save to a file.
        '''

        self.file_fields.update(values)
        with open(self.path, 'w') as f:
            yaml.dump(self.file_fields, f, sort_keys=False)

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

        try:
            cls.schema.validate(file_fields)
        except SchemaError as e:
            raise WildlandError(
                f'Error validating configuration file: {e}'
            )
        return cls(base_dir, path, default_fields, file_fields)

    @classmethod
    def get_default_fields(cls, home_dir, base_dir) -> dict:
        '''
        Compute the default values for all the unspecified fields.
        '''

        return {
            'user-dir': base_dir / 'users',
            'storage-dir': base_dir / 'storage',
            'container-dir': base_dir / 'containers',
            'bridge-dir': base_dir / 'bridges',
            'key-dir': base_dir / 'keys',
            'mount-dir': home_dir / 'wildland',
            'socket-path': base_dir / 'wlfuse.sock',
            'dummy': False,
            '@default': None,
            '@default-signer': None,
            'local-hostname': 'localhost',
            'local-signers': [],
            'default-containers': [],
        }

    @property
    def aliases(self):
        '''
        Access to aliases defined in config:

        >>> c = client.Client()
        >>> c.config.aliases['default']
        '0xaaa'
        '''
        # TODO: custom aliases (#55)
        return types.MappingProxyType({
            k: v for k, v in
                ((k[1:], self.get(k)) for k in ('@default', '@default-signer'))
            if v is not None})
