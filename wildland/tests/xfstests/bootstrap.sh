#!/usr/bin/env bash

# This script is intended to bootstrap environment for both xfstests and Wildland. xfstests which
# are used in this script are patched version of the original xfstests. The patch introduces some
# hardcoded, Wildland-specific settings.
#
# Keep in mind that this script is ran with root privileges by Vagrant. We don't care about setting
# WL up for other users then root, as xfstests care only about root. Root password is Vagrant's
# default one, e.g. `vagrant`.

apt-get -qy update

# Install xfstests deps

apt-get install -y git bc build-essential xfslibs-dev uuid-dev libtool-bin e2fsprogs automake gcc \
    libuuid1 quota attr make libacl1-dev libaio-dev xfsprogs libgdbm-dev gawk fio dbench \
    uuid-runtime python sqlite3 liburing-dev libcap-dev

# Install Wildland's deps with same pinned versions as in Wildland's Dockerfiles

apt-get install -y python3-distutils fuse3 gocryptfs time tree curl apache2 jq python3-pip \
    python3-venv libfuse-dev pkg-config

# Use --force-yes to accept the warning about encfs being insecure

apt-get install --force-yes encfs

# Free up some space

apt-get autoremove -y
apt-get clean autoclean

# Allow all users to use FUSE

echo user_allow_other >> /etc/fuse.conf

# Create and activate Python virtual environment in home directory

echo ". $HOME/env/bin/activate" >> ~/.profile

# Setup PATH for Wildland (single quotes below are on purpose to not dereference $PATH)

echo 'PATH=/opt/wildland-client:$PATH' >> ~/.profile
PATH=/opt/wildland-client:$PATH

# Create and activate Python's virtual environment

python3 -m venv ~/env/
. ~/env/bin/activate

# /opt/wildland-client is a Vagrant's synced folder with all of Wildland source code

cd /opt/wildland-client

# Install Wildland's plugins and requirements

pip install --no-cache-dir --no-warn-script-location -r requirements.base.txt
pip install --no-cache-dir --no-warn-script-location . plugins/*

# Clone Wildland-adopted xfstests fork to /opt/xfstests
# TODO FIXME clone original xfstest and apply patch instead of cloning private repo

cd /opt
git clone -b wildland-integration https://github.com/pbeza/xfstests.git

# Compile and install xfstests

cd xfstests
make
make install

# Add users and groups expected by xfstests

sudo useradd -m fsgqa || true
sudo useradd 123456-fsgqa || true
sudo useradd fsgqa2 || true

# Setup Wildland. Assume /mnt/storage is Vagrant's synced folder dedicated for tests' data.

TEST_ROOT_DIR=/mnt/storage
TEST_CONTAINER_DIR="$TEST_ROOT_DIR/xfstest-container-1"
mkdir -p "$TEST_CONTAINER_DIR"
[ "$(ls -A $TEST_CONTAINER_DIR)" ] \
    && echo "$TEST_CONTAINER_DIR synced dir is not empty; remove its content" >&2 && exit 1

wl user create User
wl container create --path / xfstests
wl storage create local --container xfstests --location "$TEST_CONTAINER_DIR"

# Create fuse.wildland filesystem type

echo '#!/usr/bin/env bash' > /sbin/mount.fuse.wildland
chmod 755 /sbin/mount.fuse.wildland

# Don't start Wildland because that is what patched xfstests are supposed to do

# wl start -s --skip-forest-mount
