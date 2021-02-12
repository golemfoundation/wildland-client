from setuptools import setup, find_packages

setup(
    name="wildland-dropbox",
    version="0.1",
    packages=find_packages(),
    entry_points={
        'wildland.storage_backends': [
            'dropbox = wildland_dropbox.backend:DropboxStorageBackend',
        ]
    },
    install_requires=[
        'dropbox',
    ],
)
