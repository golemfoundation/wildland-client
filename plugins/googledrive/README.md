# Google Drive plugin

Google Drive based read/write storage backend for Wildland containers. 

### Obtaining user credentials

Shortest way to obtain credentials is going through Step 1 in given URL: https://developers.google.com/drive/api/v3/quickstart/python#step_1_turn_on_the


Long way:
Go to Developer Console: https://console.developers.google.com/

1. Create new project
2. Enable Google Drive API
3. Press create OAuth
4. Add consent screen
5. Add Scope
6. Choose App type (Desktop)
7. Press Create OAuth (again)
8. Download credentials

When the Drive API enabled, Google will generate a client configuration file which called as credentials.json.
The content of credentials.json will look like below.

```json
{"installed":{"client_id":"{CLIENT_ID}.apps.googleusercontent.com","project_id":"{PROJECT_ID}","auth_uri":"https://accounts.google.com/o/oauth2/auth","token_uri":"https://oauth2.googleapis.com/token","auth_provider_x509_cert_url":"https://www.googleapis.com/oauth2/v1/certs","client_secret":"{CLIENT_SECRET}","redirect_uris":["urn:ietf:wg:oauth:2.0:oob","http://localhost"]}}
```
(Formatted version for readability)
```json
{
  "installed": {
    "client_id": "{CLIENT_ID}.apps.googleusercontent.com",
    "project_id": "{PROJECT_ID}",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_secret": "{CLIENT_SECRET}",
    "redirect_uris": [
      "urn:ietf:wg:oauth:2.0:oob",
      "http://localhost"
    ]
  }
}
```

### Creating Google Drive storage

```bash
wl storage create googledrive --inline --container test-container-1 --credentials 'CONTENT_OF_CLIENT_CONFIG_JSON'
```

### Mounting

```bash
wl start
wl c mount MYCONTAINER
```

### Google Drive documentation

* Google Developer Console: console.developers.google.com/
* Google Drive Python API repository: https://github.com/googleapis/google-api-python-client
* Google Drive API documentation: https://developers.google.com/drive/api/v3/about-sdk

### Issues

* Tree caching will fail if user manipulates entries from any other Google Drive client
* Some of the methods needs to be rewritten since I haven't consider performance optimizations at this stage.
* Chown and chmod are not implemented, need research if possible
* CI testing is impossible at this stage, due to interactive consent screen requirement while creating googledrive storage
* Error handling is quite immature
* Use at your own risk: Even all fundamental operations seems fine, I don't recommend to use with your personal Google Drive.
