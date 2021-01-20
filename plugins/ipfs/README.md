# IPFS Readme

IPFS backend for Wildland client. Allows to use IPFS as read-only storage for WL containers. Since publishing to IPFS (without something like Filecoin) requires additional infrastructure, writing to IPFS is not a goal. This is why this plugin limits itself to a more widely available subset of IPFS API used by gateways.

### Getting started

Installation of a local IPFS node is optional. If you want to go quick and dirty - just use a public gateway (see section below). Otherwise - install a go-ipfs client using your OS preffered way, initalize it and start it as a daemon.
```bash
wl storage create ipfs --container MYCONTAINER --ipfs-hash /ipfs/IPFS_HASH
# or
wl storage create ipfs --container MYCONTAINER --ipfs-hash /ipns/IPNS_NAME
```

### Mounting

The mounting process is no different than any other container.

```bash
wl start
wl c mount MYCONTAINER
```

The synchronisation is not implemented.

### Using IPNS

If storage is mounted using IPNS name, IPNS name needs to be resolved to IPFS CID. This process is slow. To avoid the problem of unpredictable lag, resolving is done only on mount. So, if you suspect that new data was published - just remount.

### A non-standard IPFS gateway location

This plugin expects that IPFS gateway API is exposed at '/ip4/127.0.0.1/tcp/8080/http'. You can override this setting by providing `--endpoint-addr` parameter. Example value is '/dns/ipfs.io/tcp/443/https'.

```bash
wl storage create ipfs --container MYCONTAINER --endpoint-addr /dns/ipfs.io/tcp/443/https --ipfs-hash /ipfs/CID
```

### IPFS documentation
* Network: https://docs.ipfs.io/  
* Data formats: https://docs.ipld.io/  
* How files and directories are encoded: https://github.com/ipfs/go-unixfs/blob/master/pb/unixfs.proto  
* CID explorer: https://cid.ipfs.io/  
* IPLD explorer: https://explore.ipld.io/  
* Multiformats: https://multiformats.io/

### Issues

* `ipfs add -r <mountpoint>` produces a different hash than mounted CID. Problem is likely in the way file flags are handled.
* Handles files published using default settings of `ipfs add -r`. Does not cover CIDv1 nor features marked as experimental.
