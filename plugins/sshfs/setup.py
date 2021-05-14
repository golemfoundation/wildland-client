from setuptools import setup, find_packages

setup(
    name="wildland-sshfs",
    version="0.1",
    packages=find_packages(exclude=['tests', '*.tests']),
    entry_points={
        'wildland.storage_backends': [
            'sshfs = wildland_sshfs.backend:SshFsBackend',
        ]
    },
)
