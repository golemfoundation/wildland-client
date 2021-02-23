# Wildland Project
#
# Copyright (C) 2020 Golem Foundation,
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
"""
Templates for manifests.
"""

import logging
import re
import uuid
from typing import List
from pathlib import Path
from collections import namedtuple

import yaml
from jinja2 import Template, TemplateError, StrictUndefined, UndefinedError

from wildland import container
from .manifest import Manifest

logger = logging.getLogger('wl-template')

TEMPLATE_SUFFIX = '.template.jinja'
SET_SUFFIX = '.set.yaml'

TemplateWithType = namedtuple('TemplateWithType', ['template', 'type'])


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
    '''
    Implementation of regex_replace for jinja2
    '''
    return re.sub(find, replace, s)


def regex_contains(s, pattern):
    '''
    Implementation of regex_contains for jinja2
    '''
    return re.search(pattern, s) is not None


class StorageTemplate:
    """
    Template for a storage manifest. Uses yaml and jinja2 template language.
    The template should provide a yaml file with fields filled with information need, especially
    type and any fields the given storage backend needs. Owner and container-path fields will be
    ignored.
    The following container fields can be used: uuid, categories, title, paths
    Sample local storage template:

path: /home/user/{{ uuid }}
type: local

    """

    def __init__(self, source_data: str, file_name: str, name: str = None):
        self.template = Template(source=source_data, undefined=StrictUndefined)
        self.template.environment.filters['regex_replace'] = regex_replace
        self.template.environment.tests['regex_contains'] = regex_contains
        self.file_name = file_name
        if not name:
            if self.file_name.endswith(TEMPLATE_SUFFIX):
                self.name = self.file_name[:-len(TEMPLATE_SUFFIX)]
            else:
                self.name = self.file_name
        else:
            self.name = name

    @classmethod
    def from_file(cls, path: Path):
        """
        Returns a StorageTemplate based on a yaml/jinja file
        """
        return cls(source_data=path.read_text(), file_name=path.name)

    def get_unsigned_manifest(self, cont: container.Container, local_dir: str = None):
        """
        Fill template fields with container data and return an unsigned Manifest
        """

        params = {'uuid': cont.ensure_uuid(), 'paths': cont.paths,
                  'title': cont.title if cont.title else '',
                  'categories': cont.categories, 'local_path': cont.local_path,
                  'local_dir': local_dir}

        # Filter out all null parameters
        params = {k: v for k, v in params.items() if v}

        try:
            raw_data = self.template.render(params).encode('utf-8')
        except UndefinedError as ex:
            raise ValueError(str(ex)) from ex

        data = yaml.safe_load(raw_data)
        data['owner'] = cont.owner
        data['container-path'] = str(cont.paths[0])
        data['backend-id'] = str(uuid.uuid4())
        return Manifest.from_fields(data)

    def __str__(self):
        return self.name


class StorageSet:
    """
    Set of StorageTemplates with a name. Each StorageTemplate is stored within a named tuple
    TemplateWithType which contains the StorageTemplate and a type: 'file' or 'inline'.
    'file' manifests are created as standalone files, and 'inline' as inline manifests.
    """
    def __init__(self, name: str, templates: List[TemplateWithType],
                 template_dir: Path, path: Path = None):
        self.name = name
        self.templates: List[TemplateWithType] = []
        self.path = path

        for t in templates:
            file = get_file_from_name(template_dir, t.template, TEMPLATE_SUFFIX)
            template = StorageTemplate.from_file(file)
            self.templates.append(TemplateWithType(template, t.type))

    @classmethod
    def from_file(cls, file: Path, template_dir: Path):
        """
        Loads a StorageSet from a simple yaml file that contains the following fields:
        name: name of the set
        templates: list of simple dictionaries with two fields: file (name of the template file)
        and type (file or inline)
        Type specifies if the given storage manifest should be created as a separate file or as
        inline manifest.
        """
        with open(file) as f:
            data = yaml.safe_load(f)

        name = data['name']
        templates = []
        for t in data['templates']:
            templates.append(TemplateWithType(t['file'], t['type']))
        return cls(name=name, templates=templates,
                   path=file.absolute(), template_dir=template_dir)

    def __str__(self):
        ret = self.name
        file_templates = [str(t.template) for t in self.templates if t.type == 'file']
        inline_templates = [str(t.template) for t in self.templates if t.type == 'inline']
        if file_templates:
            ret += " (file: " + ", ".join(file_templates) + ')'
        if inline_templates:
            ret += " (inline: " + ", ".join(inline_templates) + ')'
        return ret

    def to_dict(self):
        """
        Returns a dict with the same structure as a StorageSet .yaml file (see from_file)
        """
        data = {
            'name': self.name,
            'templates': [
                {'file': t.template.file_name,
                 'type': t.type} for t in self.templates
            ]
        }
        return data


class TemplateManager:
    """
    Helper class to manage StorageTemplates and StorageSets.
    """
    def __init__(self, template_dir: Path):
        self.template_dir = template_dir
        if not self.template_dir.exists():
            self.template_dir.mkdir(parents=True)

    def storage_sets(self) -> List[StorageSet]:
        """
        Returns a list of all StorageSets in template_dir; StorageSets must be correct yaml files
        ending with SET_SUFFIX(.set.yaml).
        """
        sets = []
        for file in self.template_dir.iterdir():
            if file.name.endswith(SET_SUFFIX):
                try:
                    sets.append(StorageSet.from_file(file, self.template_dir))
                except (yaml.YAMLError, KeyError):
                    logger.warning('failed to load storage template set file %s', file)
                    continue
        return sets

    def available_templates(self):
        """
        Returns a list of all StorageTemplates in template_dir; StorageTemplates must be correct
        yaml/jinja files with TEMPLATE_SUFFIX(.template.jinja)
        """
        templates = []
        for file in self.template_dir.iterdir():
            if file.name.endswith(TEMPLATE_SUFFIX):
                try:
                    templates.append(StorageTemplate.from_file(file))
                except TemplateError:
                    logger.warning('failed to load template file %s', file)
                    continue
        return templates

    def create_storage_set(self, name: str, templates: List[TemplateWithType], target_path: Path):
        """
        Create and save a StorageSet.
        :param name: str, name for the StorageSet
        :param templates: list of TemplateWithType tuples containing names of template files
        and their types (file or inline)
        :param target_path: path where the set should be saved at
        """
        # check if files exist
        template_files_with_type = []
        for template, t in templates:
            try:
                template_file = get_file_from_name(self.template_dir, template, TEMPLATE_SUFFIX)
                template_files_with_type.append(TemplateWithType(template_file.name, t))
            except FileNotFoundError:
                logger.warning('Template file not found: %s', template)
                return None

        if not templates:
            logger.error('Failed to create storage template set: no valid templates provided.')
            return None

        new_template = StorageSet(name=name, templates=template_files_with_type,
                                  template_dir=self.template_dir)
        if target_path.exists():
            raise FileExistsError

        with open(target_path, 'w') as f:
            yaml.dump(new_template.to_dict(), f)

        return target_path

    def remove_storage_set(self, name: str) -> Path:
        """
        Removes a given storage template set and return path to the removed file. Storage template
        set can be specified as filename, filename without suffix or internal storage template set
        name (as provided by the 'name' field in storage template set file).
        """
        # were we supplied with a (variant of) file name?
        storage_set = self.get_storage_set(name)
        removed_path = storage_set.path
        removed_path.unlink()
        return removed_path

    def get_storage_set(self, name):
        """
        Get StorageSet; can be specified as filename without suffix, complete filename or
        StorageSet's internal name.
        If there is more than one StorageSet with a given name, returns first one found.
        """
        try:
            storage_set = StorageSet.from_file(name, self.template_dir)
            return storage_set
        except FileNotFoundError:
            pass

        for storage_set in self.storage_sets():
            if storage_set.name == name and storage_set.path:
                return storage_set

        raise FileNotFoundError
