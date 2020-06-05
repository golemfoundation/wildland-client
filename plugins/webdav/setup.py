from setuptools import setup, find_packages

setup(
    name="wildland-webdav",
    version="0.1",
    packages=find_packages(),
    entry_points={
        'wildland.storage_backends': [
            'webdav = wildland_webdav.backend:WebdavStorageBackend',
        ]
    }
)
