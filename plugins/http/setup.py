from setuptools import setup, find_packages

setup(
    name="wildland-http",
    version="0.1",
    packages=find_packages(),
    entry_points={
        'wildland.storage_backends': [
            'http = wildland_http.backend_http:HttpStorageBackend',
        ]
    }
)
