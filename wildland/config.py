# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
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
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Configuration file handling.
"""
from pathlib import Path
from typing import Dict, Any
import os
import types

from .manifest.schema import Schema, SchemaError
from .exc import WildlandError
from .utils import yaml_parser
from .log import get_logger

logger = get_logger('config')

STANDARD_ALIASES = ['@default', '@default-owner']


class Config:
    """
    Wildland configuration, by default loaded from ~/.config/wildland/config.yaml.

    Consists of three layers:
    - default_fields (set here)
    - file_fields (loaded from file)
    - override_fields (provided from command line)
    """

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

    def get(self, name: str, use_override=True):
        """
        Get a configuration value for given name. The name has to be known,
        i.e. exist in defaults.
        """

        assert name in self.default_fields, f'unknown config name: {name}'

        if use_override:
            if name in self.override_fields:
                return self.override_fields[name]
        if name in self.file_fields:
            return self.file_fields[name]
        return self.default_fields[name]

    def override(self, dummy=False, override_fields: Dict = None):
        """
        Override configuration based on command line arguments.
        """
        if dummy:
            self.override_fields['dummy'] = True
        if override_fields:
            for name, val in override_fields.items():
                assert name in self.default_fields, f'unknown config name: {name}'
                self.override_fields[name] = val

    def update_and_save(self, values: Dict[str, Any]):
        """
        Set new values and save to a file.
        """

        self.file_fields.update(values)
        self._save_config()

    def remove_key_and_save(self, key: str):
        """
        Removes a key from the dict and saves the config file.
        """

        self.file_fields.pop(key)
        self._save_config()

    def _save_config(self):
        """
        Save fields from current ctx to the yaml file.
        """
        with open(self.path, 'w') as f:
            yaml_parser.dump(self.file_fields, f, sort_keys=False)

    @classmethod
    def update_obsolete(cls, file_fields):
        """
        Convert obsolete config entries.

        """
        if 'local-signers' in file_fields:
            logger.warning('\'local-signers\' config entry is deprecated, '
                           'use \'local-owners\' instead')
            file_fields.setdefault('local-owners', []).extend(file_fields['local-signers'])
            del file_fields['local-signers']

        if '@default-signer' in file_fields:
            logger.warning('\'@default-signer\' config entry is deprecated, '
                           'use \'@default-owner\' instead')
            file_fields.setdefault('@default-owner', file_fields['@default-signer'])
            del file_fields['@default-signer']

        if len(file_fields.get('@default-owner', '')) == 22:
            logger.warning('\'@default-owner\' uses obsolete Signify key format. '
                           'Please update to the new format.')

        if len(file_fields.get('@default', '')) == 22:
            logger.warning('\'@default\' uses obsolete Signify key format. '
                           'Please update to the new format.')

        for owner in file_fields.get('local-owners', []):
            if len(owner) == 22:
                logger.warning('Owner %s in \'local-owners\' uses obsolete Signify key '
                               'format. Please update to the new format.', owner)

        if 'default-storage-set-for-user' in file_fields:
            logger.warning('\'default-storage-set-for-user\' config entry is deprecated and no '
                           'longer in use. Remove it from your config.yaml')
            del file_fields['default-storage-set-for-user']

    @classmethod
    def load(cls, base_dir=None):
        """
        Load a configuration file from base directory, if it exists; use
        defaults if not.
        """

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
                file_fields = yaml_parser.load(f)
                if not file_fields:
                    file_fields = {}
        else:
            file_fields = {}

        cls.update_obsolete(file_fields)

        try:
            cls.schema.validate(file_fields)
        except SchemaError as e:
            raise WildlandError(
                f'Error validating configuration file: {e}'
            ) from e

        cls.validate_aliases(file_fields)
        return cls(base_dir, path, default_fields, file_fields)

    @classmethod
    def get_default_fields(cls, home_dir, base_dir) -> dict:
        """
        Compute the default values for all the unspecified fields.
        """

        return {
            'user-dir': base_dir / 'users',
            'storage-dir': base_dir / 'storage',
            'cache-dir': base_dir / 'cache',
            'container-dir': base_dir / 'containers',
            'bridge-dir': base_dir / 'bridges',
            'key-dir': base_dir / 'keys',
            'mount-dir': home_dir / 'wildland',
            'template-dir': base_dir / 'templates',
            'fs-socket-path': Path(os.getenv('XDG_RUNTIME_DIR', str(base_dir))) / 'wlfuse.sock',
            'sync-socket-path': Path(os.getenv('XDG_RUNTIME_DIR', str(base_dir))) / 'wlsync.sock',
            'alt-bridge-separator': False,
            'dummy': False,
            '@default': None,
            '@default-owner': None,
            'aliases': {},
            'local-hostname': 'localhost',
            'local-owners': [],
            'default-containers': [],
            'default-remote-for-container': {},
            'default-cache-template': None,
        }

    @staticmethod
    def validate_aliases(file_fields):
        """
        Validate the configuration to check if it doesn't contain any custom
        aliases that collide with standard ones.
        """

        custom_aliases = file_fields.get('aliases', {})
        for key in STANDARD_ALIASES:
            if key in custom_aliases:
                raise WildlandError(f'{key} cannot be a custom alias')

    @property
    def aliases(self):
        """
        Access to aliases defined in config:

        >>> c = client.Client()
        >>> c.config.aliases['default']
        '0xaaa'
        """

        result = {}
        custom_aliases = self.get('aliases')
        for key in STANDARD_ALIASES:
            assert key not in custom_aliases
            value = self.get(key)
            if value is not None:
                result[key[1:]] = value

        for key, value in custom_aliases.items():
            result[key[1:]] = value

        return types.MappingProxyType(result)
