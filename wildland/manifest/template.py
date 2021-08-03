# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
#                    Marta Marczykowska-Górecka <marmarta@invisiblethingslab.com>,
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
Templates for manifests.
"""

import re
import uuid
from typing import List, Optional, Union
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import yaml
from jinja2 import Template, TemplateError, StrictUndefined, UndefinedError

from wildland.wildland_object.wildland_object import WildlandObject
from wildland import container
from .manifest import Manifest
from ..client import Client
from ..utils import load_yaml
from ..exc import WildlandError
from ..storage import Storage
from ..storage_backends.base import StorageBackend
from ..log import get_logger

logger = get_logger('wl-template')

TEMPLATE_SUFFIX = '.template.jinja'


def get_file_from_name(directory: Path, name: str, suffix: str) -> Path:
    """
    Tries to disambiguate a potentially ambiguous name: tests if it's the complete file name
    or the file name without suffix. Returns Path with file, or raises FileNotFoundError if no
    appropriate file could be found.
    """
    candidate_files = [directory / name, directory / (name + suffix)]
    for file in candidate_files:
        if file.exists():
            return file
    raise FileNotFoundError


# Custom jinja2 filters
def regex_replace(s, find, replace):
    """
    Implementation of regex_replace for jinja2
    """
    return re.sub(find, replace, s)


def regex_contains(s, pattern) -> bool:
    """
    Implementation of regex_contains for jinja2
    """
    return re.search(pattern, s) is not None


class StorageTemplate:
    """
    Single storage template object for a storage manifest. See :class:`TemplateFile` class for
    details on defining a list of such objects.
    """

    def __init__(self, source_data: Union[str, dict]):
        if isinstance(source_data, dict):
            source_data = yaml.dump(source_data)

        assert isinstance(source_data, str)  # satisfy mypy
        self.template = Template(source=source_data, undefined=StrictUndefined)
        self.template.environment.filters['regex_replace'] = regex_replace
        self.template.environment.tests['regex_contains'] = regex_contains

    def get_storage_fields(self, cont: container.Container, local_dir: Optional[str] = None):
        """
        Fill template fields with container data and return them.
        """

        params = {'uuid': cont.uuid, 'paths': cont.paths,
                  'title': cont.title if cont.title else '',
                  'categories': cont.categories, 'local_path': cont.local_path,
                  'local_dir': local_dir, 'version': Manifest.CURRENT_VERSION,
                  'owner': cont.owner}

        # Filter out all null parameters
        params = {k: v for k, v in params.items() if v}

        try:
            raw_data = self.template.render(params).encode('utf-8')
        except UndefinedError as ex:
            raise ValueError(str(ex)) from ex

        data = load_yaml(raw_data)
        data['owner'] = cont.owner
        data['container-path'] = str(cont.paths[0])
        data['backend-id'] = str(uuid.uuid4())
        return cont.fill_storage_fields(data)

    def get_storage(self, client: Client, cont: container.Container, local_dir: Optional[str]) \
            -> Storage:
        """
        Return Storage object corresponding to this storage template.
        """
        storage_fields = self.get_storage_fields(cont, local_dir)
        if 'type' not in storage_fields:
            raise WildlandError('Type of the storage missing in given template.')
        storage_type = storage_fields['type']
        storage_cls = StorageBackend.types()[storage_type]

        if storage_cls.LOCATION_PARAM and storage_cls.LOCATION_PARAM in storage_fields and \
                storage_fields[storage_cls.LOCATION_PARAM]:
            orig_location = storage_fields[storage_cls.LOCATION_PARAM]

            if client.is_url(orig_location):
                uri = urlparse(orig_location)
                path = Path(uri.path).resolve()
                location = urlunparse(
                    (uri.scheme, uri.netloc, str(path), uri.params, uri.query, uri.fragment))
            else:
                location = orig_location

            storage_fields[storage_cls.LOCATION_PARAM] = str(location)

        return WildlandObject.from_fields(storage_fields, client, WildlandObject.Type.STORAGE,
            local_owners=client.config.get('local-owners'))


class TemplateFile:
    """
    Defines physical file that holds list of :class:`StorageTemplate` in yaml format using jinja2
    template language. The template file should provide a yaml file with array of objects where each
    object contains fields required for a specific type of storage backend, especially backend type.
    Owner and container-path fields will be ignored.

    The following container fields can be used: ``uuid``, ``categories``, ``title``, ``paths``,
    ``local_path``, ``owner``. Sample local storage template file::

        - type: local
        location: /home/user/{{ uuid }}
        - type: dropbox
        location: /subdir_in_dropbox{{ local_dir if local_dir is defined else "" }}/{{ uuid }}
        read-only: true
        token: dropbox_secret_token
    """

    def __init__(self, path: Path):
        self.file_path = path
        self.templates = self._load_templates()

    def _load_templates(self) -> List[StorageTemplate]:
        if not self.file_path.exists():
            raise WildlandError(f'Template file [{self.file_path}] does not exist.')

        with self.file_path.open() as f:
            return [StorageTemplate(source_data=data) for data in load_yaml(f)]

    def __lt__(self, other):
        return str(self) < str(other)

    def __str__(self):
        file_name = self.file_path.name

        if file_name.endswith(TEMPLATE_SUFFIX):
            return file_name[:-len(TEMPLATE_SUFFIX)]

        return file_name


class TemplateManager:
    """
    Helper class to manage :class:`TemplateFile` and :class:`StorageTemplate`.
    """

    def __init__(self, template_dir: Path):
        self.template_dir = template_dir
        if not self.template_dir.exists():
            self.template_dir.mkdir(parents=True)

    def get_file_path(self, name: str) -> Path:
        """
        Return path to :class:`TemplateFile` based on given name.

        :param name: Can be either an absolute path to a file or a template name inside template_dir
        """
        default_path = self.template_dir / (name + str(TEMPLATE_SUFFIX))

        file_candidates: List[Union[Path, str]] = [
            name,
            self.template_dir / name,
            default_path,
        ]

        for file in file_candidates:
            path = Path(file)
            logger.debug('Looking for template: %s', path)
            if Path(name).exists():
                return Path(name)

        # Existing file not found, assuming default path for newly created file
        logger.debug('Existing template not found. Returning default path %s', default_path)
        return default_path

    @staticmethod
    def is_valid_template_file_path(path: Path) -> bool:
        """
        Return true if given path has a valid :class:`TemplateFile` name.
        """
        return path.name.endswith(TEMPLATE_SUFFIX)

    def available_templates(self) -> List[TemplateFile]:
        """
        Returns a list of all :class:`TemplateFile` in template_dir; :class:`TemplateFile` must be
        correct yaml/jinja files with ``TEMPLATE_SUFFIX``.
        """
        templates = []
        for file in self.template_dir.iterdir():
            if self.is_valid_template_file_path(file):
                try:
                    templates.append(TemplateFile(file))
                except TemplateError:
                    logger.warning('failed to load template file %s', file)
                    continue
        return templates

    def get_storage_template(self, name: str) -> StorageTemplate:
        """
        Get StorageTemplate; can be specified as filename without suffix, complete filename or
        StorageTemplate's internal name.
        If there is more than one StorageTemplate with a given name, returns first one found.
        """
        return self.get_template_file_by_name(name).templates[0]

    def get_template_file_by_name(self, template_name: str) -> TemplateFile:
        """
        Return :class:`TemplateFile` object for a given template name.
        """
        target_path = self.get_file_path(template_name)

        return TemplateFile(target_path)

    def create_storage_template(self, template_name: str, params: dict) -> Path:
        """
        Create storage template from given, arbitrary params and append to a given template file.
        If template file doesn't exist, create it and then append the template.
        """
        target_path = self.get_file_path(template_name)
        yaml_contents = []

        if target_path.exists():
            with open(target_path, 'r') as f:
                yaml_contents = list(load_yaml(f))

        yaml_contents.append(params)

        with open(target_path, 'w') as f:
            yaml.dump(yaml_contents, f)

        return target_path

    def remove_storage_template(self, name: str) -> None:
        """
        Remove storage template by name.
        """
        target_path = self.get_file_path(name)

        if not target_path.exists():
            raise FileNotFoundError

        target_path.unlink()
