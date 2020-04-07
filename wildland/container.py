#
# (c) 2020 Wojtek Porczyk <woju@invisiblethingslab.com>
#

import pathlib
import urllib.parse
import urllib.request
import uuid

from voluptuous import Schema, All, Any, Length, Coerce

from .storage import AbstractStorage
from .storage_control import control_directory, control_file
from .storage_local import LocalStorage

from .manifest import Manifest
from .sig import DummySigContext


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
        return open(path, 'rb')

    @staticmethod
    def load_http(url, **_kwds):
        return urllib.request.urlopen(urllib.parse.urlunsplit(url))


class Container:
    '''Wildland container'''
    STORAGE = {
        'local': LocalStorage,
    }

    SCHEMA = Schema({
        'signer': All(str),
        'uuid': All(Coerce(uuid.UUID)),
        'paths': All(list, Length(min=1)),
        'backends': {'storage': [str]},
    }, required=True)
    SCHEMA_STORAGE = Schema({
        'type': Any(*STORAGE),
    }, required=True, extra=True)

    _load = _DataLoader()

    def __init__(self, *, manifest: Manifest, storage: AbstractStorage):
        self.manifest = manifest
        self.ident = manifest.fields['uuid']
        #: list of paths, under which this container should be mounted
        self.paths = manifest.fields['paths']

        #: the chosen storage instance
        self.storage = storage

    @classmethod
    def from_yaml_file(cls, path: pathlib.Path):
        '''Load from file-like object with container manifest (a YAML document).
        '''
        with open(path, 'rb') as f:
            content = f.read()

        return cls.from_yaml_content(content, path.parent)

    @classmethod
    def from_yaml_content(cls, content: bytes, dirpath: pathlib.Path = None):
        # TODO verify real signatures
        sig_context = DummySigContext()

        manifest = Manifest.from_bytes(content, sig_context, schema=cls.SCHEMA)

        for smurl in manifest.fields['backends']['storage']:
            smurl = urllib.parse.urlsplit(smurl, scheme='file')
            try:
                with cls._load(smurl, relative_to=dirpath) as smfile:
                    # TODO verify signature
                    storage_manifest_content = smfile.read()
            except UnsupportedURLSchemeError:
                continue

            storage_manifest = Manifest.from_bytes(
                storage_manifest_content, sig_context)

            try:
                storage_cls = cls.STORAGE[storage_manifest.fields['type']]
            except KeyError:
                continue

            storage_manifest.apply_schema(storage_cls.SCHEMA)

            storage = storage_cls(manifest=storage_manifest, relative_to=dirpath)

            return cls(manifest=manifest, storage=storage)

        raise TypeError('no supported storage manifest URL scheme')

    @control_directory('storage')
    def control_storage(self):
        yield '0', self.storage

    @control_file('manifest.yaml')
    def control_manifest_read(self):
        return self.manifest.to_bytes()
