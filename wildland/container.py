#
# (c) 2020 Wojtek Porczyk <woju@invisiblethingslab.com>
#

'''
The container
'''


import pathlib
import urllib.parse
import urllib.request

from .storage import AbstractStorage
from .storage_control import control_directory, control_file
from .storage_local import LocalStorage
from .storage_s3 import S3Storage

from .manifest.manifest import Manifest, ManifestError
from .manifest.loader import ManifestLoader
from .manifest.schema import Schema


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

    # pylint: disable=missing-docstring

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
        's3': S3Storage,
    }

    SCHEMA = Schema('container')

    _load = _DataLoader()

    def __init__(self, *, manifest: Manifest, storage: AbstractStorage):
        self.manifest = manifest
        #: list of paths, under which this container should be mounted
        self.paths = manifest.fields['paths']

        #: the chosen storage instance
        self.storage = storage

    @classmethod
    def from_yaml_file(cls, path: pathlib.Path, loader: ManifestLoader):
        '''Load from file-like object with container manifest (a YAML document).
        '''
        with open(path, 'rb') as f:
            content = f.read()

        return cls.from_yaml_content(content, loader, path.parent)

    @classmethod
    def from_yaml_content(cls, content: bytes, loader: ManifestLoader,
                          dirpath: pathlib.Path = None):
        '''Load from YAML-formatted data'''
        manifest = loader.parse_manifest(content, schema=cls.SCHEMA)

        for smurl in manifest.fields['backends']['storage']:
            smurl = urllib.parse.urlsplit(smurl, scheme='file')
            try:
                with cls._load(smurl, relative_to=dirpath) as smfile:
                    storage_manifest_content = smfile.read()
            except UnsupportedURLSchemeError:
                continue

            storage_manifest = loader.parse_manifest(
                storage_manifest_content,
                schema=AbstractStorage.SCHEMA)
            storage_type = storage_manifest.fields['type']

            try:
                storage_cls = cls.STORAGE[storage_type]
            except KeyError:
                continue

            storage_manifest.apply_schema(storage_cls.SCHEMA)

            # Verify storage
            if storage_manifest.fields['signer'] != manifest.fields['signer']:
                raise ManifestError(
                    'Signer field mismatch: storage {}, container {}'.format(
                        storage_manifest.fields['signer'], manifest.fields['signer']))
            if storage_manifest.fields['container_path'] not in manifest.fields['paths']:
                raise ManifestError(
                    'Unrecognized container path for storage: {}, {}'.format(
                        storage_manifest.fields['container_path'], manifest.fields['paths']))

            uid = loader.config.get('uid')
            gid = loader.config.get('gid')

            storage = storage_cls(manifest=storage_manifest,
                                  relative_to=dirpath,
                                  uid=uid, gid=gid)

            return cls(manifest=manifest, storage=storage)

        raise ManifestError('no supported storage manifest URL scheme')

    # pylint: disable=missing-docstring

    @control_directory('storage')
    def control_storage(self):
        yield '0', self.storage

    @control_file('manifest.yaml')
    def control_manifest_read(self):
        return self.manifest.to_bytes()
