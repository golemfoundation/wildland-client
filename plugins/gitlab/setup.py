from setuptools import setup, find_packages

setup(
    name="wildland-gitlab",
    version="0.1",
    packages=find_packages(),
    entry_points={
        'wildland.storage_backends': [
            'gitlab = wildland_gitlab.backend:GitlabStorageBackend',
        ]
    },
    install_requires=[
        'python-gitlab',
    ],

)


