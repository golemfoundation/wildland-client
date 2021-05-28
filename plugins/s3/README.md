# S3 Readme
S3 backend for Wildland client

### Getting started

Create your container just as any other container and add S3 as a storage.

```bash
wl storage create s3 --container MYCONTAINER --s3-url s3://MY_BUCKET_NAME/PATH --access-key MY_ACCESS_KEY
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

### Notes for --with-index flag

The `--with-index` flag is used for s3 backend to generate index files (named `/` -- yes, just slash) which are used by a HTTP server (ie. CDN or S3 web access) to serve directory listing, very similar to directory listing used in Apache web server.

It is important to remember that those index files are refreshed only when a file or directory is modified using wildland storage backend thus the index might not be up-to-date if you modify a file or directory outside of wildland (ie. directly in the S3 bucket). The same applies if you disable `with-index` parameter and then re-enable it again (ie. it will not cause indexes to refresh until a file or directory is modified within a specific directory).

### Non-AWS S3 endpoint

Should you have a S3-compatible backend, which is not hosted on AWS, you must specify its location using `--endpoint-url` S3 storage option and thus overriding the default endpoint URL generation in the AWS S3 sdk.

As an example, for locally hosted minio server on port 9000, you want the storage creation command to look like so:

```bash
wl storage create --container MYCONTAINER --endpoint-url 'http://127.0.0.1:9000' --s3-url s3://MY_BUCKET_NAME/
```

**Note:** Using this option still relies on credentials specified through aws-cli client (ie `aws configure`) although the _default region_ param will not be used to generate the endpoint url like it would if you used the default AWS-endpoint generation mechanism.
