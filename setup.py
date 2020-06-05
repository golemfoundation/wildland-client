from setuptools import setup, find_packages

setup(
    name="widland-fuse",
    version="0.1",
    packages=find_packages(),
    entry_points={
        'wildland.storage_backends': [
            'local = wildland.storage_backends.local:LocalStorageBackend',
            'local_cached = wildland.storage_backends.local_cached:LocalCachedStorageBackend',
        ]
    }
)
