from setuptools import setup, find_packages

setup(
    name="wildland-imap",
    version="0.1",
    packages=find_packages(exclude=['tests', '*.tests']),
    entry_points={
        'wildland.storage_backends': [
            'imap = wildland_imap.backend:ImapStorageBackend',
        ]
   }
)
