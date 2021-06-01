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
Abstract class representing all Wildland Objects (Users, Containers, Bridges, Storages, Links.
"""
import abc
import enum
import typing
from wildland.manifest.schema import Schema
from wildland.manifest.manifest import Manifest, ManifestError


class WildlandObject(abc.ABC):
    """
    Abstract class representing Wildland Objects. To implement it, implement parse_fields and
    to_manifest_fields at minimum. If implementing from_manifest, make sure fields are
    correctly validated.

    WildlandObject should own all objects contained within; if passing dicts (e.g. as
    manifests-catalog or backends), deepcopy them.
    """
    class Type(enum.Enum):
        """
        Possible Wildland object types.
        """
        USER = 'user'
        BRIDGE = 'bridge'
        STORAGE = 'storage'
        CONTAINER = 'container'
        TEMPLATE = 'template'
        LINK = 'link'

    _subclasses: typing.Dict[Type, typing.Type['WildlandObject']] = {}

    CURRENT_VERSION = '1'  # when updating, update also in schemas/types.json
    SCHEMA: typing.Optional[Schema] = None

    @abc.abstractmethod
    def __init__(self, *args, **kwargs):
        self.manifest = None

    @classmethod
    def from_fields(cls, fields: dict, client, object_type: typing.Optional[Type] = None,
                    manifest: typing.Optional[Manifest] = None, **kwargs):
        """
        Initialize a WildlandObject from a dict of fields. Will verify if the dict fits
        a schema, if object_type supports a schema.
        This method should NOT be reimplemented by inheriting classes, in order to
        make sure verification was correctly done.
        :param fields: dict of fields
        :param client: Wildland Client object, used to load any needed supplementary objects
        :param object_type: WildlandObject.Type; if loads an unexpected type, will raise an
        error
        :param manifest: if the object is constructed from manifest, pass this manifest here
        :param kwargs: any additional keyword arguments, may be used by WL object inits.
        :return: an instanced WildlandObject
        """
        if object_type:
            class_name = fields.get('object', object_type.value)
            if not class_name == object_type.value:
                raise ManifestError(f'Unexpected object type: expected {object_type.value}, '
                                    f'received {class_name}')
        else:
            class_name = fields.get('object', None)
        class_type = WildlandObject.Type(class_name)

        object_class = cls._subclasses[class_type]
        if object_class.SCHEMA:
            object_class.SCHEMA.validate(fields)

        return object_class.parse_fields(fields, client, manifest, **kwargs)

    @classmethod
    @abc.abstractmethod
    def parse_fields(cls, fields: dict, client,
                     manifest: typing.Optional[Manifest] = None, **kwargs):
        """
        Initialize a WildlandObject from a dict of fields. Will verify if the dict fits
        a schema, if object_type supports a schema.
        :param fields: dict of fields
        :param client: Wildland Client object, used to load any needed supplementary objects
        :param object_type: WildlandObject.Type; if loads an unexpected type, will raise an
        error
        :param manifest: if the object is constructed from manifest, pass this manifest here
        :param kwargs: any additional keyword arguments, may be used by WL object inits.
        :return: an instanced WildlandObject
        """

    @classmethod
    def from_manifest(cls, manifest: Manifest, client,
                      object_type: typing.Optional[Type] = None, **kwargs):
        """
        Create a Wildland Object from a provided Manifest
        :param manifest: source Manifest; must be verified or trusted
        :param client: Wildland Client object, used to load any needed supplementary objects
        :param object_type: WildlandObject.Type; if loads an unexpected type, will raise an
        error
        :param kwargs: any additional keyword arguments, may be used by WL object inits.
        :return: an instanced WildlandObject
        """
        return cls.from_fields(manifest.fields, client, object_type=object_type, manifest=manifest,
                               **kwargs)

    def __init_subclass__(cls, obj_type=None, **kwargs):
        # Annotated due to mypy bug: https://github.com/python/mypy/issues/4660
        super().__init_subclass__(**kwargs)  # type: ignore
        if obj_type:
            cls._subclasses[obj_type] = cls

    @abc.abstractmethod
    def to_manifest_fields(self, inline: bool) -> dict:
        """
        Return a dict with fields ready to be put inside a manifest (inline or standalone).
        The dict can be later modified, so be careful and deepcopy when needed.

        When implementing, take care to verify that returned fields are valid
        (through self.SCHEMA.validate or other appropriate methods).
        """

    @property
    def local_path(self):
        """
        Local file path of the object.
        """
        if self.manifest:
            return self.manifest.local_path
        return None
