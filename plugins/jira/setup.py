from setuptools import setup, find_packages

setup(
    name="wildland-jira",
    version="0.1",
    packages=find_packages(),
    entry_points={
        'wildland.storage_backends': [
            'jira = wildland_jira.backend:JiraStorageBackend',
        ]
    },
    install_requires=[
        'requests',
    ],

)


