# Wildland xfstests

This Vagrant-based virtual environment is intended to be used as a `xfstests` test suite for testing
Wildland. Note that original `xfstests` repository needed to be patched to support Wildland.


## Running the tests

To run the tests make sure `libvirtd` service is running on your host machine:

```console
$ sudo systemctl start libvirtd
$ vagrant up --provider=libvirt
```

Running vagrant requires either `root` privileges or `libvirt` group membership. To check if your
user is already in this group, run `id` command. If you don't want to retype the user password every
time you spin up your Vagrant environment, make sure to add your user to `libvirt` group by running:

```console
$ sudo usermod -a -G libvirt `whoami`
```

To run the selected test (i.e. `tests/generic/001`), run:

```console
vagrant@bullseye:~$ vagrant ssh
vagrant@bullseye:~$ su -  # root is required for xfstests to be ran; password: vagrant
(env) root@bullseye:~# cd /opt/xfstests/
(env) root@bullseye:/opt/xfstests# ./check-wildland tests/generic/001
```

If you want to run all of the tests available just skip `tests/generic/001` param.

If you want to rerun Vagrant's provisioning script, run:

```console
$ vagrant provision
```

If you modified `Vagrantfile`, run:

```console
$ vagrant reload
```

If you want to clear up Vagrant environment, run:

```
$ vagrant destroy
$ vagrant box remove debian/bullseye64
```
