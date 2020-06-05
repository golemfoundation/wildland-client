from setuptools import setup, find_packages

setup(
    name="wildland-fuse",
    version="0.1",
    packages=find_packages(),
    package_data={'wildland': ['schemas/*.json']},
    entry_points={
        'wildland.storage_backends': [
            'local = wildland.storage_backends.local:LocalStorageBackend',
            'local_cached = wildland.storage_backends.local_cached:LocalCachedStorageBackend',
        ]
    }
)