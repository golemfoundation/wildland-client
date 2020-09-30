Proxy storage (experimental)
============================

A *proxy storage* is a storage that is parametrized by another, "inner"
storage.

Right now we have one example: ``date-proxy``. It's a storage that sorts files
according to the modification time. For example, if a file ``foo.txt`` has a
modification time of 2020-05-01, it will be available under
``2020/05/01/foo.txt``.

Example (using CLI)
-------------------

Create a user, if you haven't done that yet::

   $ ./wl user create User


Create the "inner" container, and directory with files::

   $ ./wl container create Inner --path /inner

   $ ./wl storage create local Inner --path $HOME/proxy-data \
       --container Inner
   $ mkdir ~/proxy-data
   $ touch ~/proxy-data/file1.txt -t 202005010000
   $ touch ~/proxy-data/file2.txt -t 201905010000

Create the proxy container storage::

   $ ./wl container create Proxy --path /proxy

   $ ./wl storage create date-proxy Proxy \
       --inner-container-url file://$HOME/.config/wildland/containers/Inner.yaml \
       --container Proxy

Mount::

   $ ./wl start
   $ ./wl container mount Proxy

You should be able to see the files::

   $ find ~/wildland/proxy/
   /home/user/wildland/proxy/
   /home/user/wildland/proxy/2019
   /home/user/wildland/proxy/2019/05
   /home/user/wildland/proxy/2019/05/01
   /home/user/wildland/proxy/2019/05/01/file2.txt
   /home/user/wildland/proxy/2020
   /home/user/wildland/proxy/2020/05
   /home/user/wildland/proxy/2020/05/01
   /home/user/wildland/proxy/2020/05/01/file1.txt

Example (self-contained manifest
--------------------------------

All manifests can be inlined. You can create a ``container.yaml``
file (or edit existing one using ``wl container edit``)

.. code-block:: yaml

   owner: <OWNER>
   paths:
     - /.uuid/11e69833-0152-4563-92fc-b1540fc54a69
     - /proxy

   backends:
     storage:
       - type: date-proxy
         container-path: /.uuid/11e69833-0152-4563-92fc-b1540fc54a69
         owner: <OWNER>
         inner-container:
           owner: <OWNER>
           paths:
             - /inner
           backends:
             storage:
               - type: local
                 container-path: /.uuid/11e69833-0152-4563-92fc-b1540fc54a69
                 owner: <OWNER>
                 path: /home/user/proxy-data

This file can be signed with ``wl container sign`` (the edit command will do
that automatically), then mounted using ``wl container mount``.
