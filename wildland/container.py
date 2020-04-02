#
# (c) 2020 Wojtek Porczyk <woju@invisiblethingslab.com>
#

import pathlib
import urllib.parse
import urllib.request

import yaml

from voluptuous import Schema, All, Any, Length

from .storage_control import control
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

    # pylint: disable=missing-docstring

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
        'paths': All(list, Length(min=1)),
        'backends': {'storage': [str]},
    }, required=True)
    SCHEMA_STORAGE = Schema({
        'type': Any(*STORAGE),
    }, required=True, extra=True)

    _load = _DataLoader()

    def __init__(self, fs, paths, storage):
        self.fs = fs

        #: list of paths, under which this container should be mounted
        self.paths = paths

        #: the chosen storage instance
        self.storage = storage

    @staticmethod
    def verify_signature(file):
        '''Verify a signature

        This method currently does nothing.
        '''
        # TODO: signature verification
        return file

    @classmethod
    def fromyaml(cls, fs, file):
        '''Load from file-like object with container manifest (a YAML document).
        '''
        data = cls.SCHEMA(yaml.safe_load(cls.verify_signature(file)))
        dirpath = pathlib.Path(file.name).parent

        for smurl in data['backends']['storage']:
            smurl = urllib.parse.urlsplit(smurl, scheme='file')
            try:
                with cls._load(smurl, relative_to=dirpath) as smfile:
                    smdata = cls.SCHEMA_STORAGE(
                        yaml.safe_load(cls.verify_signature(smfile)))
            except UnsupportedURLSchemeError:
                continue

            try:
                storage_type = cls.STORAGE[smdata['type']]
            except KeyError:
                continue

            return cls(
                fs=fs,
                paths=data['paths'],
                storage=storage_type.fromdict(smdata,
                    fs=fs, relative_to=dirpath))

        raise TypeError('no supported storage manifest URL scheme')

    @control('storage', directory=True)
    def control_storage(self):
        yield '0', self.storage
