# pylint: disable=missing-docstring,redefined-outer-name,too-many-lines,unused-import

from wildland.tests.conftest import cli, base_dir


def test_container_publish_to_s3(monkeypatch, cli):
    class Timestamp:
        @staticmethod
        def timestamp():
            return 0

    class Client:
        COUNTER = 0

        def __init__(self):
            self.objects = {}

        def list_objects_v2(self, **kwargs):
            assert kwargs
            Client.COUNTER += 1
            return {'IsTruncated': False,
                    'NextContinuationToken': None,
                    'Contents': list(self.objects.values())}

        def get_object(self, **kwargs):
            return self.objects[kwargs['Key']]

        def head_object(self, **kwargs):
            try:
                return self.objects[kwargs['Key']]
            except KeyError as e:
                raise FileNotFoundError() from e

        def put_object(self, **kwargs) -> None:
            self.objects[kwargs['Key']] = {'Key': kwargs['Key'],
                                           'Size': kwargs['Body'].getbuffer().nbytes
                                           if 'Body' in kwargs else 0,
                                           'ETag': "",
                                           'LastModified': Timestamp,
                                           'Body': kwargs['Body'] if 'Body' in kwargs else None,
                                           'ContentType': kwargs['ContentType']
                                           if 'ContentType' in kwargs else None}

        def delete_object(self, **kwargs) -> None:
            self.objects.pop(kwargs['Key'])

    class Session:
        def __init__(self, *args, **kwargs):
            pass

        @staticmethod
        def client(**kwargs):
            assert kwargs
            return Client()

    monkeypatch.setattr('boto3.Session', Session)
    monkeypatch.setattr('wildland.storage_backends.cached.CachedStorageMixin.CACHE_TIMEOUT', -1)

    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--update-user',
        '--category', '/a', '--category', '/b', '--category', '/c',
        '--category', '/d', '--category', '/e', '--category', '/f')
    cli('storage', 'create', 's3', 'S3Storage',
        '--container', 'Container',
        '--inline',
        '--manifest-pattern', '/{path}.yaml',
        '--s3-url', 's3://foo-location/path',
        '--endpoint-url', 'http://foo-location.com',
        '--access-key', 'foo-access-key',
        '--secret-key', 'foo-secret-key')

    cli('container', 'publish', 'Container')

    assert Client.COUNTER == 3
