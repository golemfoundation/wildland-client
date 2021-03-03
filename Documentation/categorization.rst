Categorization storage
======================

Categorization storage is a storage that is parametrized by another "reference" storage. Based on
the category tags embedded into directories' names in the referenced storage, it builds
subcontainers that expose categories' trees.


Directory tree categorization
-----------------------------

In order to categorize directory tree we introduce the following directories' naming convention:

1. Putting a ``@`` symbol anywhere in the filesystem path symbolizes beginning of a new category.

2. That category is taken to extent until the occurrence of the next ``@`` symbol or until the last
   directory segment.

3. The last directory segment (e.g. ``title1``) is considered a container's title.

4. The underscores (``_``) are considered as equivalent to slashes (``/``) in category paths. This
   is to allow more flat filesystem structures, if preferred by the user. E.g. there is no need to
   create ``author2/@titles/title3/`` nested dirs -- it's enough to have just one dir named
   ``author2_@titles_title3/``.

See an example::

  books/
  `-- @authors
      |-- author1
      |   |-- @titles_title1          # <- prefixed with '@titles'
      |   |   |-- book.epub
      |   |   `-- book.pdf
      |   `-- @titles_title2          # <- prefixed with '@titles'
      |       `-- skan.pdf
      |-- author2_@titles_title3      # <- reordered author, added '@title' in between
      |   `-- ocr.epub
      `-- author3_@titles_title4      # <- new dir created (each container is a dir)
          `-- title.epub

The above naming convention applies only to directories. Categories embedded into filenames are
ignored.


``categorization`` examples (using CLI)
---------------------------------------

Example 1
~~~~~~~~~

Lets start with creating a directory tree that will be used in referenced container::

  $ tree -a ~/storage/categorization-test/
  /home/user/storage/categorization-test/
  `-- @authors
      |-- author1
      |   |-- @titles_title1
      |   |   |-- book.epub
      |   |   `-- book.pdf
      |   `-- @titles_title2
      |       `-- skan.pdf
      |-- author2_@titles_title3
      |   `-- ocr.epub
      `-- author3_@titles_title4
          `-- title.epub
  6 directories, 5 files

Now, start Wildland driver and create an user, if you haven't done that yet::

  $ wl start
  $ wl user create your_username

Create referenced container and attach storage to it::

  $ wl container create --path /local mylocal
  $ wl storage create local \
      --container mylocal \
      --location ~/storage/categorization-test/

In the above example we attached local storage but you can make use of any other supported storage.
Now create a "proxy" container for categorization storage and attach storage to it::

  $ wl container create --path /categorization categorization_container
  $ wl storage create categorization \
      --container categorization_container \
      --reference-container-url file://$HOME/.config/wildland/containers/mylocal.container.yaml

Mount categorization container, which is kind of a proxy view on the referenced  container (which is
``mylocal`` in our case)::

  $ wl c mount categorization_container
  new: /home/user/.config/wildland/containers/categorization_container.container.yaml
  new: /home/user/.config/wildland/containers/categorization_container.container.yaml:/.uuid/8e1976a4-4259-3475-afff-f9266f31eafe
  new: /home/user/.config/wildland/containers/categorization_container.container.yaml:/.uuid/7c43d0b9-76f9-3f14-b465-89fcfaffd819
  new: /home/user/.config/wildland/containers/categorization_container.container.yaml:/.uuid/4390ef41-9693-31e7-bbf3-456cd4800ad6
  new: /home/user/.config/wildland/containers/categorization_container.container.yaml:/.uuid/0b03a71b-282f-3b64-80de-80ded6385f03
  Mounting 5 containers

Now you can list the mountpoints::

  $ ls -la mnt
  total 8
  dr-xr-xr-x 1 user user    0 Jan  1  1970 ./
  drwxr-xr-x 1 user user 4096 Feb 26 14:52 ../
  dr-xr-xr-x 1 user user    0 Jan  1  1970 .users/
  dr-xr-xr-x 1 user user    0 Jan  1  1970 .uuid/
  dr-xr-xr-x 1 user user    0 Jan  1  1970 authors/
  dr-xr-xr-x 1 user user    0 Jan  1  1970 categorization/
  dr-xr-xr-x 1 user user    0 Jan  1  1970 titles/

You can see that besides ``categorization`` directory, which is just a mirror of what you can find
in ``/home/user/storage/categorization-test/`` directory, there were also 2 other directories
created (``authors`` and ``titles``) that correspond to the categories read from referenced
directory tree. If you would add ``--only-subcontainers`` flag to the ``wl c mount`` command, there
would be no ``categorization`` directory in the above listing.

Now lets list ``authors`` directory::

  $ tree -a mnt/authors/
  mnt/authors/
  |-- author1
  |   |-- @titles
  |   |   |-- title1
  |   |   |   |-- book.epub
  |   |   |   `-- book.pdf
  |   |   `-- title2
  |   |       `-- skan.pdf
  |   |-- title1
  |   |   |-- book.epub
  |   |   `-- book.pdf
  |   `-- title2
  |       `-- skan.pdf
  |-- author2
  |   |-- @titles
  |   |   `-- title3
  |   |       `-- ocr.epub
  |   `-- title3
  |       `-- ocr.epub
  `-- author3
      |-- @titles
      |   `-- title4
      |       `-- title.epub
      `-- title4
          `-- title.epub

  14 directories, 10 files

and ``titles`` directory::

  $ tree -a mnt/titles
  mnt/titles
  |-- @authors
  |   |-- author1
  |   |   |-- title1
  |   |   |   |-- book.epub
  |   |   |   `-- book.pdf
  |   |   `-- title2
  |   |       `-- skan.pdf
  |   |-- author2
  |   |   `-- title3
  |   |       `-- ocr.epub
  |   `-- author3
  |       `-- title4
  |           `-- title.epub
  |-- title1
  |   |-- book.epub
  |   `-- book.pdf
  |-- title2
  |   `-- skan.pdf
  |-- title3
  |   `-- ocr.epub
  `-- title4
      `-- title.epub

     12 directories, 10 files

To list all mounted containers, including 4 subcontainers, run::

  $ wl status --with-subcontainers
  Mounted containers:

  /.uuid/eaad7132-7a96-4bb1-bb75-aef6ee302afe
    storage: categorization
    paths:
      /.uuid/eaad7132-7a96-4bb1-bb75-aef6ee302afe
      /.users/0x28d1cd2e32d577856445/.uuid/eaad7132-7a96-4bb1-bb75-aef6ee302afe
      /categorization
      /.users/0x28d1cd2e32d577856445/categorization

  /.uuid/1e8e5942-e4c6-3180-9cb9-9bd7303b48fa
    storage: delegate
    paths:
      /.uuid/1e8e5942-e4c6-3180-9cb9-9bd7303b48fa
      /.users/0x28d1cd2e32d577856445/.uuid/1e8e5942-e4c6-3180-9cb9-9bd7303b48fa
      /authors/author3/title4
      /.users/0x28d1cd2e32d577856445/authors/author3/title4
      /titles/title4
      /.users/0x28d1cd2e32d577856445/titles/title4
      /authors/author3/@titles/title4
      /.users/0x28d1cd2e32d577856445/authors/author3/@titles/title4
      /titles/@authors/author3/title4
      /.users/0x28d1cd2e32d577856445/titles/@authors/author3/title4
    subcontainer-of: 0x28d1cd2e32d577856445:/.uuid/eaad7132-7a96-4bb1-bb75-aef6ee302afe

  /.uuid/211be870-8301-3c28-a4bd-0b237d505a14
    storage: delegate
    paths:
      /.uuid/211be870-8301-3c28-a4bd-0b237d505a14
      /.users/0x28d1cd2e32d577856445/.uuid/211be870-8301-3c28-a4bd-0b237d505a14
      /authors/author1/title1
      /.users/0x28d1cd2e32d577856445/authors/author1/title1
      /titles/title1
      /.users/0x28d1cd2e32d577856445/titles/title1
      /authors/author1/@titles/title1
      /.users/0x28d1cd2e32d577856445/authors/author1/@titles/title1
      /titles/@authors/author1/title1
      /.users/0x28d1cd2e32d577856445/titles/@authors/author1/title1
    subcontainer-of: 0x28d1cd2e32d577856445:/.uuid/eaad7132-7a96-4bb1-bb75-aef6ee302afe

  /.uuid/edfed29d-cfc4-3341-8917-fe0c77a9378c
    storage: delegate
    paths:
      /.uuid/edfed29d-cfc4-3341-8917-fe0c77a9378c
      /.users/0x28d1cd2e32d577856445/.uuid/edfed29d-cfc4-3341-8917-fe0c77a9378c
      /titles/title3
      /.users/0x28d1cd2e32d577856445/titles/title3
      /authors/author2/title3
      /.users/0x28d1cd2e32d577856445/authors/author2/title3
      /titles/@authors/author2/title3
      /.users/0x28d1cd2e32d577856445/titles/@authors/author2/title3
      /authors/author2/@titles/title3
      /.users/0x28d1cd2e32d577856445/authors/author2/@titles/title3
    subcontainer-of: 0x28d1cd2e32d577856445:/.uuid/eaad7132-7a96-4bb1-bb75-aef6ee302afe

  /.uuid/f98462b7-8636-3f38-8257-aff4935b05dd
    storage: delegate
    paths:
      /.uuid/f98462b7-8636-3f38-8257-aff4935b05dd
      /.users/0x28d1cd2e32d577856445/.uuid/f98462b7-8636-3f38-8257-aff4935b05dd
      /authors/author1/title2
      /.users/0x28d1cd2e32d577856445/authors/author1/title2
      /titles/title2
      /.users/0x28d1cd2e32d577856445/titles/title2
      /authors/author1/@titles/title2
      /.users/0x28d1cd2e32d577856445/authors/author1/@titles/title2
      /titles/@authors/author1/title2
      /.users/0x28d1cd2e32d577856445/titles/@authors/author1/title2
    subcontainer-of: 0x28d1cd2e32d577856445:/.uuid/eaad7132-7a96-4bb1-bb75-aef6ee302afe


Example 2
~~~~~~~~~

If you follow the same steps as in the above example, but on the following directory tree instead::

  test/
  |-- @ala
  |   `-- ma_kota
  |       `-- test.txt
  `-- @ala_ma
      `-- kota
          `-- test.txt

you will get the following mountpoints::

  $ ls -la mnt
  total 8
  dr-xr-xr-x 1 user user    0 Jan  1  1970 ./
  drwxr-xr-x 1 user user 4096 Feb 26 15:30 ../
  dr-xr-xr-x 1 user user    0 Jan  1  1970 .users/
  dr-xr-xr-x 1 user user    0 Jan  1  1970 .uuid/
  dr-xr-xr-x 1 user user    0 Jan  1  1970 ala/
  dr-xr-xr-x 1 user user    0 Jan  1  1970 categorization/

  $ tree -a mnt/ala/
  mnt/ala/
  `-- ma
      `-- kota
          |-- test.wl_12.txt
          `-- test.wl_13.txt

  2 directories, 2 files

  $ tree -a mnt/categorization/
  mnt/categorization/
  |-- @ala
  |   `-- ma_kota
  |       `-- test.txt
  `-- @ala_ma
      `-- kota
          `-- test.txt

  4 directories, 2 files

Note that Wildland autorenamed files to mount all ``test.txt`` files in the same category path.

To list all mounted containers, including 4 subcontainers, run::

  $ wl status --with-subcontainers
  Mounted containers:

  /.uuid/b974ba4d-8acb-4a4c-9c2f-cf511c338d4c
    storage: categorization
    paths:
      /.uuid/b974ba4d-8acb-4a4c-9c2f-cf511c338d4c
      /.users/0x28d1cd2e32d577856445/.uuid/b974ba4d-8acb-4a4c-9c2f-cf511c338d4c
      /categorization
      /.users/0x28d1cd2e32d577856445/categorization

  /.uuid/2077b80c-2b90-3f1f-a046-cfddacf51f04
    storage: delegate
    paths:
      /.uuid/2077b80c-2b90-3f1f-a046-cfddacf51f04
      /.users/0x28d1cd2e32d577856445/.uuid/2077b80c-2b90-3f1f-a046-cfddacf51f04
      /ala/ma/kota
      /.users/0x28d1cd2e32d577856445/ala/ma/kota
    subcontainer-of: 0x28d1cd2e32d577856445:/.uuid/b974ba4d-8acb-4a4c-9c2f-cf511c338d4c

  /.uuid/020bbbd4-ec83-3e65-9c93-d7428e06333d
    storage: delegate
    paths:
      /.uuid/020bbbd4-ec83-3e65-9c93-d7428e06333d
      /.users/0x28d1cd2e32d577856445/.uuid/020bbbd4-ec83-3e65-9c93-d7428e06333d
      /ala/ma/kota
      /.users/0x28d1cd2e32d577856445/ala/ma/kota
    subcontainer-of: 0x28d1cd2e32d577856445:/.uuid/b974ba4d-8acb-4a4c-9c2f-cf511c338d4c
