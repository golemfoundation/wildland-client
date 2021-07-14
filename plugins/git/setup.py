from setuptools import setup, find_packages

setup(
    name="wildland-git",
    version="0.1",
    packages=find_packages(),
    entry_points={
        'wildland.storage_backends': [
            'git = wildland_git.backend:GitStorageBackend',
        ]
    },
    install_requires=[
        'GitPython'
    ],
)

