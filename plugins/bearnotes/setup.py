from setuptools import setup, find_packages

setup(
    name="wildland-bearnotes",
    version="0.1",
    packages=find_packages(),
    entry_points={
        'wildland.storage_backends': [
            'bear-db = wildland_bearnotes.backend:BearDBStorageBackend',
            'bear-note = wildland_bearnotes.backend:BearNoteStorageBackend',
        ]
    }
)
