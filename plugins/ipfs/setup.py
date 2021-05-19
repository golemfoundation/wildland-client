from setuptools import setup, find_packages

setup(
    name="wildland-ipfs",
    version="0.1",
    packages=find_packages(),
    entry_points={
        'wildland.storage_backends': [
            'ipfs = wildland_ipfs.backend:IPFSStorageBackend'
        ]
    },
    install_requires=[
        'ipfshttpclient'
    ],

)
