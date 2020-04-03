#
# (c) 2020 Wojtek Porczyk <woju@invisiblethingslab.com>
#

import pathlib
import urllib.parse
import urllib.request
import uuid

import yaml

from voluptuous import Schema, All, Any, Length, Coerce

from .storage import AbstractStorage
from .storage_control import control_directory
from .storage_local import LocalStorage

class UnsupportedURLSchemeError(Exception):
    '''Raised when URL scheme is unsupported by loader'''

class _DataLoader:
    '''Loader for fetching external files

    The files should be designated using URI
    FIXME: RFC number

    >>> load = _DataLoader()
    >>> load('http://httpbin.org/get').read()

    On success, a file-like object is returned. On failure, either
    :py:class:`UnsupportedURLSchemeError` is raised or an error specific to URL
    scheme.

    To implement another URL scheme, write ``load_<scheme>`` method.
    '''
    def __call__(self, url, **kwds):
        try:
            method = getattr(self, f'load_{url.scheme}')
        except AttributeError:
            raise UnsupportedURLSchemeError(
                f'unsupported URL scheme: {url.scheme!r}')

        return method(url, **kwds)

    @staticmethod
    def load_file(url, *, relative_to=None, **_kwds):
        assert not url.netloc
        path = pathlib.Path(url.path)
        if relative_to is not None:
            path = relative_to / path
        return open(path)

    @staticmethod
    def load_http(url, **_kwds):
        return urllib.request.urlopen(urllib.parse.urlunsplit(url))


class Container:
    '''Wildland container'''
    STORAGE = {
        'local': LocalStorage,
    }

    SCHEMA = Schema({
        'uuid': All(Coerce(uuid.UUID)),
        'paths': All(list, Length(min=1)),
        'backends': {'storage': [str]},
    }, required=True)
    SCHEMA_STORAGE = Schema({
        'type': Any(*STORAGE),
    }, required=True, extra=True)

    _load = _DataLoader()

    def __init__(self, *, fs, ident: uuid.UUID, paths, storage: AbstractStorage):
        self.fs = fs
        self.ident = ident

        #: list of paths, under which this container should be mounted
        self.paths = paths

        #: the chosen storage instance
        self.storage = storage

    @classmethod
    def from_yaml_file(cls, fs, path: pathlib.Path):
        '''Load from file-like object with container manifest (a YAML document).
        '''
        with open(path, 'rb') as f:
            content = f.read()

        return cls.from_yaml_content(fs, content, path.parent)

    @classmethod
    def from_yaml_content(cls, fs, content: bytes, dirpath: pathlib.Path = None):
        # TODO verify signature
        data = cls.SCHEMA(yaml.safe_load(content))

        for smurl in data['backends']['storage']:
            smurl = urllib.parse.urlsplit(smurl, scheme='file')
            try:
                with cls._load(smurl, relative_to=dirpath) as smfile:
                    # TODO verify signature
                    smdata = cls.SCHEMA_STORAGE(
                        yaml.safe_load(smfile))
            except UnsupportedURLSchemeError:
                continue

            try:
                storage_type = cls.STORAGE[smdata['type']]
            except KeyError:
                continue

            storage = storage_type.fromdict(smdata, relative_to=dirpath)

            return cls(
                fs=fs,
                ident=data['uuid'],
                paths=data['paths'],
                storage=storage)

        raise TypeError('no supported storage manifest URL scheme')

    @control_directory('storage')
    def control_storage(self):
        yield '0', self.storage
