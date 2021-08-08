from setuptools import setup, find_packages

setup(
    name="wildland-gitlab-graphql",
    version="0.1",
    packages=find_packages(),
    entry_points={
        'wildland.storage_backends': [
            'gitlab-graphql = wildland_gitlabql.backend:GitlabQLStorageBackend',
        ]
    },
    install_requires=[
        'requests',
    ],

)


