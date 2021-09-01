from setuptools import setup, find_packages
from wildland import __version__

setup(
    name="wildland-client",
    version=__version__,
    packages=find_packages(),
    package_data={'wildland': ['schemas/*.json']},
    entry_points={
        'wildland.storage_backends': [
            'local = wildland.storage_backends.local:LocalStorageBackend',
            'local_cached = wildland.storage_backends.local_cached:LocalCachedStorageBackend',
            ('local_dir_cached = '
             'wildland.storage_backends.local_cached:LocalDirectoryCachedStorageBackend'),
            'dummy = wildland.storage_backends.dummy:DummyStorageBackend',
            'static = wildland.storage_backends.static:StaticStorageBackend',
            ('pseudomanifest = '
             'wildland.storage_backends.pseudomanifest:PseudomanifestStorageBackend'),
            'date_proxy = wildland.storage_backends.date_proxy:DateProxyStorageBackend',
            'delegate = wildland.storage_backends.delegate:DelegateProxyStorageBackend',
            'transpose = wildland.storage_backends.transpose:TransposeStorageBackend',
            'http = wildland.storage_backends.http:HttpStorageBackend',
        ],
        'wildland.storage_sync': [
            'naive = wildland.storage_sync.naive_sync:NaiveSyncer'
        ]
    }
)
