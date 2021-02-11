Conflict resolution
===================

Wildland will allow you to mount multiple containers under the same path, or
under overlapping paths. In such cases, the goal is for all the files to be
available. Instead of hiding some directories or files, Wildland will make a
best effort to *merge* the mounted containers.

Note that the below applies to the FUSE driver. Other parts of the system do
not perform conflict resolution.

Merging directories
-------------------

If a given directory is available in two mounted containers, the directories
will be merged. That means:

1. Files from both directories will be available. You will be able to read and
   write to them.

2. In case of files with the same names, the files will be visible under a
   modified name. The name is created adding ``.wl.STORAGE_ID`` suffix, where
   ``STORAGE_ID`` is an internal identifier of the FUSE driver.

   The name change is local; the file is still kept under the original name in
   the backing storage, and visible under the original name under other paths.

3. It is not possible to modify a merged directory, i.e. add or remove files or
   directories.

Note that despite the above restriction, conflicts might still be introduced by
modifying one of the containers. That will cause the files to change their
visible names suddenly, which might break some programs using them.

Example
-------

Let's say we have two containers:

* Container 1 is mounted under `/Photos` and under `/.uuid/UUID1`, and contains
  the following files::

      2020-01-01/
        a.jpg
        b.jpg

      2020-01-02/
        a.jpg
        b.jpg

* Container 2 is mounted under `/Photos` and `/.uuid/UUID2`, and contains the
  following files::

      2020-01-02/
        b.jpg
        c.jpg

The mounted files and directories will be as follows::

    Photos/
      2020-01-01/
        a.jpg
        b.jpg

      2020-01-02/
        a.jpg
        b.jpg.wl.1
        b.jpg.wl.2
        c.jpg

    .uuid/
       UUID1/
         2020-01-01/
           a.jpg
           b.jpg
         2020-01-02/
           a.jpg
           b.jpg

       UUID2/
         2020-01-02/
           b.jpg
           c.jpg

The ``Photos/2020-01-02`` folder is read-only, you are not allowed to add,
remove or rename files in it. However, you can still modify the source
directories using the ``.uuid/`` paths.
