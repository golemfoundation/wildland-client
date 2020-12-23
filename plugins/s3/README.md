# S3 Readme
S3 backend for Wildland client

### Getting started

The S3 backend will need your S3 key/secret/region details but will not prompt you to provide them neither in the stdin nor as the cli args. Instead, they’ll be fetched from your aws-cli client. 

```bash
$ python -m pip install [--user] awscli
$ aws configure
AWS Access Key ID: MYACCESSKEY
AWS Secret Access Key: MYSECRETKEY
Default region name [us-west-2]: eu-north-1
Default output format [None]: json
```

Proceed with adding  new wild land backend as usual.

```bash
wl storage create s3 --container MYCONTAINER --s3-url s3://MY_BUCKET_NAME/PATH
```

**Note:** If you want your backend to point to the root path of the bucket (thus listing all files in your bucket) remember about the trailing slash after the bucket’s name.

```bash
wl storage create --container MYCONTAINER --s3-url s3://MY_BUCKET_NAME/ # <--- (trailing slash)
```

### Mounting

The mounting process is no different than any other container

```bash
wl start
wl c mount MYCONTAINER
```

The synchronisation is automatic and files are not fetched from the server until opened thus it may take a while to open a large file.

### Non-AWS S3 endpoint

Should you have a S3-compatible backend, which is not hosted on AWS, you must specify its location using `--endpoint-url` S3 storage option and thus overriding the default endpoint URL generation in the AWS S3 sdk.

As an example, for locally hosted minio server on port 9000, you want the storage creation command to look like so:

```bash
wl storage create --container MYCONTAINER --endpoint-url 'http://127.0.0.1:9000' --s3-url s3://MY_BUCKET_NAME/
```

**Note:** Using this option still relies on credentials specified through aws-cli client (ie `aws configure`) although the _default region_ param will not be used to generate the endpoint url like it would if you used the default AWS-endpoint generation mechanism.
