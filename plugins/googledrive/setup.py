from setuptools import setup, find_packages

setup(
    name="wildland-googledrive",
    version="0.1",
    packages=find_packages(),
    entry_points={
        'wildland.storage_backends': [
            'googledrive = wildland_googledrive.backend:DriveStorageBackend',
        ]
    },
    install_requires=[
        'google-api-python-client',
        'google-auth-httplib2',
        'google-auth-oauthlib',
        'httplib2shim',
        'treelib'
    ],
)
