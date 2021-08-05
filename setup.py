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
            'encrypted = wildland.storage_backends.encrypted:EncryptedStorageBackend',
            'delegate = wildland.storage_backends.delegate:DelegateProxyStorageBackend',
            'zip_archive = wildland.storage_backends.zip_archive:ZipArchiveStorageBackend',
            ('categorization_proxy = '
             'wildland.storage_backends.categorization_proxy:CategorizationProxyStorageBackend'),
        ],
        'wildland.storage_sync': [
            'naive = wildland.storage_sync.naive_sync:NaiveSyncer'
        ]
    }
)
