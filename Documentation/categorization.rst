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


Categorization examples (using CLI)
-----------------------------------

Example 1
~~~~~~~~~

Lets start with creating a directory tree that will be used in the referenced container::

  $ tree -a ~/storage/books/
  /home/user/storage/books/
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

Create the referenced container and attach some storage to it::

  $ wl container create --path /local mylocal
  $ wl storage create local \
      --container mylocal \
      --location ~/storage/books/

In the above example we attached a local storage but you can make use of any other supported
storage. Now create a "proxy" container for categorization storage and attach the storage created
above to it::

  $ wl container create --path /categorization categorization_container
  $ wl storage create categorization \
      --container categorization_container \
      --reference-container-url file://$HOME/.config/wildland/containers/mylocal.container.yaml

Mount categorization container, which is kind of a proxy view on the referenced  container (which is
``mylocal`` in our case)::

  $ wl c mount categorization_container
  new: 0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963:['/.uuid/6b4afcc0-07e2-48fc-b741-0c3204d2e105', '/categorization'] (/home/user/.config/wildland/containers/categorization_container.container.yaml)
  new: 0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963:['/.uuid/6b4afcc0-07e2-48fc-b741-0c3204d2e105', '/categorization'] (/home/user/.config/wildland/containers/categorization_container.container.yaml):/.uuid/3f3a2bb0-a6c9-3f51-bdbe-797856fb8c1e
  new: 0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963:['/.uuid/6b4afcc0-07e2-48fc-b741-0c3204d2e105', '/categorization'] (/home/user/.config/wildland/containers/categorization_container.container.yaml):/.uuid/aa1e7997-13e6-3982-abb0-427d9704ff8a
  new: 0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963:['/.uuid/6b4afcc0-07e2-48fc-b741-0c3204d2e105', '/categorization'] (/home/user/.config/wildland/containers/categorization_container.container.yaml):/.uuid/cd008a7f-fc6f-31c8-8173-730f863cf8a7
  new: 0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963:['/.uuid/6b4afcc0-07e2-48fc-b741-0c3204d2e105', '/categorization'] (/home/user/.config/wildland/containers/categorization_container.container.yaml):/.uuid/a532884b-1783-38d4-a0b9-0adcfb6857f1
  Mounting 5 containers

Now you can list the mountpoints::

  $ ls -la mnt
  total 12
  dr-xr-xr-x 1 user user    0 Jan  1  1970 ./
  drwxr-xr-x 1 user user 4096 Mar 24 13:54 ../
  dr-xr-xr-x 1 user user    0 Jan  1  1970 .backends/
  dr-xr-xr-x 1 user user    0 Jan  1  1970 .users/
  dr-xr-xr-x 1 user user    0 Jan  1  1970 .uuid/
  dr-xr-xr-x 1 user user    0 Jan  1  1970 authors/
  dr-xr-xr-x 1 user user 4096 Mar 24 13:48 categorization/
  dr-xr-xr-x 1 user user    0 Jan  1  1970 titles/

You can see that besides ``categorization`` directory, which is just a mirror of what you can find
in ``/home/user/storage/books/`` directory, there were also 2 other directories created (``authors``
and ``titles``) that correspond to the categories read from referenced directory tree. If you would
add ``--only-subcontainers`` flag to the ``wl c mount`` command, there would be no
``categorization`` directory in the above listing.

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

  /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/.backends/6b4afcc0-07e2-48fc-b741-0c3204d2e105/e68c2ff4-bed1-4425-9fb1-c8e1164638a9
    storage: categorization
    paths:
      /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/.backends/6b4afcc0-07e2-48fc-b741-0c3204d2e105/e68c2ff4-bed1-4425-9fb1-c8e1164638a9
      /.backends/6b4afcc0-07e2-48fc-b741-0c3204d2e105/e68c2ff4-bed1-4425-9fb1-c8e1164638a9
      /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/.uuid/6b4afcc0-07e2-48fc-b741-0c3204d2e105
      /.uuid/6b4afcc0-07e2-48fc-b741-0c3204d2e105
      /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/categorization
      /categorization

  /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/.backends/3f3a2bb0-a6c9-3f51-bdbe-797856fb8c1e/3f3a2bb0-a6c9-3f51-bdbe-797856fb8c1e
    storage: delegate
    paths:
      /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/.backends/3f3a2bb0-a6c9-3f51-bdbe-797856fb8c1e/3f3a2bb0-a6c9-3f51-bdbe-797856fb8c1e
      /.backends/3f3a2bb0-a6c9-3f51-bdbe-797856fb8c1e/3f3a2bb0-a6c9-3f51-bdbe-797856fb8c1e
      /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/.uuid/3f3a2bb0-a6c9-3f51-bdbe-797856fb8c1e
      /.uuid/3f3a2bb0-a6c9-3f51-bdbe-797856fb8c1e
      /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/titles/title3
      /titles/title3
      /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/authors/author2/title3
      /authors/author2/title3
      /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/titles/@authors/author2/title3
      /titles/@authors/author2/title3
      /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/authors/author2/@titles/title3
      /authors/author2/@titles/title3
    subcontainer-of: 0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963:/.uuid/6b4afcc0-07e2-48fc-b741-0c3204d2e105

  /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/.backends/aa1e7997-13e6-3982-abb0-427d9704ff8a/aa1e7997-13e6-3982-abb0-427d9704ff8a
    storage: delegate
    paths:
      /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/.backends/aa1e7997-13e6-3982-abb0-427d9704ff8a/aa1e7997-13e6-3982-abb0-427d9704ff8a
      /.backends/aa1e7997-13e6-3982-abb0-427d9704ff8a/aa1e7997-13e6-3982-abb0-427d9704ff8a
      /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/.uuid/aa1e7997-13e6-3982-abb0-427d9704ff8a
      /.uuid/aa1e7997-13e6-3982-abb0-427d9704ff8a
      /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/authors/author1/title2
      /authors/author1/title2
      /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/titles/title2
      /titles/title2
      /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/authors/author1/@titles/title2
      /authors/author1/@titles/title2
      /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/titles/@authors/author1/title2
      /titles/@authors/author1/title2
    subcontainer-of: 0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963:/.uuid/6b4afcc0-07e2-48fc-b741-0c3204d2e105

  /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/.backends/cd008a7f-fc6f-31c8-8173-730f863cf8a7/cd008a7f-fc6f-31c8-8173-730f863cf8a7
    storage: delegate
    paths:
      /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/.backends/cd008a7f-fc6f-31c8-8173-730f863cf8a7/cd008a7f-fc6f-31c8-8173-730f863cf8a7
      /.backends/cd008a7f-fc6f-31c8-8173-730f863cf8a7/cd008a7f-fc6f-31c8-8173-730f863cf8a7
      /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/.uuid/cd008a7f-fc6f-31c8-8173-730f863cf8a7
      /.uuid/cd008a7f-fc6f-31c8-8173-730f863cf8a7
      /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/authors/author3/title4
      /authors/author3/title4
      /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/titles/title4
      /titles/title4
      /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/authors/author3/@titles/title4
      /authors/author3/@titles/title4
      /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/titles/@authors/author3/title4
      /titles/@authors/author3/title4
    subcontainer-of: 0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963:/.uuid/6b4afcc0-07e2-48fc-b741-0c3204d2e105

  /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/.backends/a532884b-1783-38d4-a0b9-0adcfb6857f1/a532884b-1783-38d4-a0b9-0adcfb6857f1
    storage: delegate
    paths:
      /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/.backends/a532884b-1783-38d4-a0b9-0adcfb6857f1/a532884b-1783-38d4-a0b9-0adcfb6857f1
      /.backends/a532884b-1783-38d4-a0b9-0adcfb6857f1/a532884b-1783-38d4-a0b9-0adcfb6857f1
      /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/.uuid/a532884b-1783-38d4-a0b9-0adcfb6857f1
      /.uuid/a532884b-1783-38d4-a0b9-0adcfb6857f1
      /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/authors/author1/title1
      /authors/author1/title1
      /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/titles/title1
      /titles/title1
      /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/authors/author1/@titles/title1
      /authors/author1/@titles/title1
      /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/titles/@authors/author1/title1
      /titles/@authors/author1/title1
    subcontainer-of: 0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963:/.uuid/6b4afcc0-07e2-48fc-b741-0c3204d2e105


Example 2
~~~~~~~~~

Lets see what happens if you follow the same steps as in the example above, but on the following
directory tree instead::

  $ tree -a /home/user/life
  /home/user/life
  |-- @art
  |   |-- books
  |   |   `-- @authors
  |   |       |-- Agatha\ Christie
  |   |       |   |-- @titles_Death\ on\ the\ Nile
  |   |       |   |   `-- nile.pdf
  |   |       |   |-- @titles_Murder\ in\ Mesopotamia
  |   |       |   |   |-- book\ cover
  |   |       |   |   |   `-- cover.jpg
  |   |       |   |   `-- mesopotamia.pdf
  |   |       |   |-- @titles_The\ Big\ Four
  |   |       |   |   `-- big4.pdf
  |   |       |   |-- @titles_The\ Secret\ Adversary
  |   |       |   |   `-- secret-adversary.epub
  |   |       |   `-- Christie_biography.txt
  |   |       `-- J.K.\ Rowling
  |   |           `-- @titles
  |   |               |-- Harry\ Potter
  |   |               |   |-- Harry\ Potter\ and\ the\ Chamber\ of\ Secrets
  |   |               |   |   `-- HP_chamber.pdf
  |   |               |   |-- Harry\ Potter\ and\ the\ Philosopher's\ Stone
  |   |               |   |   `-- HP_stone.pdf
  |   |               |   `-- Harry\ Potter\ and\ the\ Prisoner\ of\ Azkaban
  |   |               |       `-- azkaban.pdf
  |   |               `-- The\ Ickabog
  |   |                   |-- ickabog.dvi
  |   |                   `-- ickabog.pdf
  |   `-- movies
  |       `-- Star\ Wars
  |           |-- Episode\ IV\ \342\200\223\ A\ New\ Hope
  |           |   |-- episode4.mp4
  |           |   `-- eposiode4_subtitles.rst
  |           |-- Episode\ V\ \342\200\223\ The\ Empire\ Strikes\ Back
  |           `-- Star\ Wars\ history.txt
  |-- @science
  |   |-- Computer\ Science
  |   |   |-- @papers_cryptography_elliptic\ curves
  |   |   |   |-- ec-latest.pdf
  |   |   |   `-- ec.pdf
  |   |   |-- @papers_hardware_intel
  |   |   |   |-- intel-paper-1.pdf
  |   |   |   `-- intel-paper-2.pdf
  |   |   `-- index.html
  |   `-- Maths
  |       |-- Algebra
  |       |   |-- algebra_pub.pdf
  |       |   `-- algebra_report.md
  |       `-- Discrete\ mathematics
  |           |-- paper.pdf
  |           `-- paper.tex
  `-- @travels
      |-- business
      |   |-- ABC\ Company
      |   |   |-- @places_US
      |   |   |   `-- Texas_Austin
      |   |   |       |-- austin_1.jpg
      |   |   |       `-- austin_2.jpg
      |   |   |-- @places_US_Dallas
      |   |   |   `-- dallas.rar
      |   |   |-- @places_US_NYC
      |   |   |   |-- Brooklyn
      |   |   |   |   |-- brooklyn\ 1.jpg
      |   |   |   |   |-- brooklyn\ 2.jpg
      |   |   |   |   |-- brooklyn\ 3.jpg
      |   |   |   |   `-- brooklyn\ 4.jpg
      |   |   |   `-- Manhattan
      |   |   |       |-- manhattan\ 1.jpg
      |   |   |       |-- manhattan\ 2.jpg
      |   |   |       |-- manhattan\ 3.jpg
      |   |   |       `-- manhattan\ 4.jpg
      |   |   `-- @places_US_Zanzibar
      |   |       |-- zanzibar_1.jpg
      |   |       |-- zanzibar_2.jpg
      |   |       |-- zanzibar_3.jpg
      |   |       |-- zanzibar_4.jpg
      |   |       |-- zanzibar_5.jpg
      |   |       |-- zanzibar_6.jpg
      |   |       |-- zanzibar_7.jpg
      |   |       |-- zanzibar_8.jpg
      |   |       `-- zanzibar_9.jpg
      |   |-- Great\ Company\ @places_Poland_Krakow
      |   |   |-- address.txt
      |   |   `-- krakow_office.jpg
      |   |-- Great\ Company\ @places_Poland_Warsaw
      |   |   |-- gcompany\ office\ 1.jpg
      |   |   |-- gcompany\ office\ 2.jpg
      |   |   |-- gcompany\ office\ 3.jpg
      |   |   |-- gcompany\ office\ 4.jpg
      |   |   |-- gcompany\ office\ 5.jpg
      |   |   `-- index.html
      |   `-- My\ business\ travel\ card.pdf
      |-- planned
      |   `-- List\ of\ places\ to\ visit.txt
      `-- private
          |-- @places_Poland_Tricity
          |   |-- Gdansk
          |   |   |-- Cool\ places\ in\ Gdansk.txt
          |   |   |-- Oliwa
          |   |   |   |-- @hotels
          |   |   |   |   |-- 5*\ Cool\ Hotel
          |   |   |   |   |   |-- bed.jpg
          |   |   |   |   |   |-- lunch.jpg
          |   |   |   |   |   |-- patio.jpg
          |   |   |   |   |   |-- pricing.txt
          |   |   |   |   |   `-- room.jpg
          |   |   |   |   `-- Hotel\ Oliwski
          |   |   |   |       |-- patio.jpg
          |   |   |   |       |-- prices.txt
          |   |   |   |       |-- room1.jpg
          |   |   |   |       `-- room2.jpg
          |   |   |   `-- @restaurants
          |   |   |       |-- Gdansk\ Oliwa\ other\ restaurants.txt
          |   |   |       |-- Mandu
          |   |   |       |   |-- menu.txt
          |   |   |       |   |-- pierogi.jpg
          |   |   |       |   `-- pierogi2.jpg
          |   |   |       `-- Restaurant\ at\ the\ train\ station
          |   |   |           |-- menu.pdf
          |   |   |           `-- myfood.jpg
          |   |   `-- Wrzeszcz
          |   |       |-- Gdansk_Wrzeszcz_apartment.jpg
          |   |       `-- fav_places_in_Gdansk-Wrzeszcz.txt
          |   |-- Gdynia
          |   |   `-- Orlowo_pier\ @nature
          |   |       |-- beautiful_sunset.jpg
          |   |       `-- pier.jpg
          |   `-- Sopot
          |       `-- Places\ to\ visit\ in\ Sopot.txt
          `-- @places_US_California
              |-- California-1.jpg
              |-- California-2.jpg
              |-- California-3.jpg
              |-- California-4.jpg
              `-- California-5.jpg

  55 directories, 79 files

you will get the following mountpoints (mounted with ``--only-subcontainers`` flag)::

  $ ls -la mnt
  total 8
  dr-xr-xr-x 1 user user    0 Jan  1  1970 ./
  drwxr-xr-x 1 user user 4096 Mar 24 13:11 ../
  dr-xr-xr-x 1 user user    0 Jan  1  1970 .backends/
  dr-xr-xr-x 1 user user    0 Jan  1  1970 .users/
  dr-xr-xr-x 1 user user    0 Jan  1  1970 .uuid/
  dr-xr-xr-x 1 user user    0 Jan  1  1970 art/
  dr-xr-xr-x 1 user user    0 Jan  1  1970 authors/
  dr-xr-xr-x 1 user user    0 Jan  1  1970 hotels/
  dr-xr-xr-x 1 user user    0 Jan  1  1970 papers/
  dr-xr-xr-x 1 user user    0 Jan  1  1970 places/
  dr-xr-xr-x 1 user user    0 Jan  1  1970 restaurants/
  dr-xr-xr-x 1 user user    0 Jan  1  1970 science/
  dr-xr-xr-x 1 user user    0 Jan  1  1970 titles/
  dr-xr-xr-x 1 user user    0 Jan  1  1970 travels/

To get all of the book titles available, run::

  $ tree -a -L 1 mnt/art/books/@titles/
  mnt/art/books/@titles/
  |-- Death\ on\ the\ Nile
  |-- Harry\ Potter
  |-- Murder\ in\ Mesopotamia
  |-- The\ Big\ Four
  |-- The\ Ickabog
  `-- The\ Secret\ Adversary

  6 directories, 0 files

You can achieve the same by listing ``mnt/titles``.

To list all book titles written by *Agatha Christie* and *J. K. Rowling* respectively, run::

  $ tree -a -L 1 "mnt/authors/Agatha Christie/@titles"
  mnt/authors/Agatha\ Christie/@titles
  |-- Death\ on\ the\ Nile
  |-- Murder\ in\ Mesopotamia
  |-- The\ Big\ Four
  `-- The\ Secret\ Adversary

  4 directories, 0 files

  $ tree -a -L 1 "mnt/authors/J.K. Rowling/@titles/"
  mnt/authors/J.K.\ Rowling/@titles/
  |-- Harry\ Potter
  `-- The\ Ickabog

  2 directories, 0 files

To list all of the places visited on business trips together with *ABC Company*, run::

  $ tree -a -L 2 mnt/travels/business/ABC\ Company/@places/
  mnt/travels/business/ABC\ Company/@places/
  `-- US
      |-- Dallas
      |-- NYC
      |-- Texas
      `-- Zanzibar

  5 directories, 0 files

To list only those places that were visited privately, run::

  mnt/travels/private/@places/
  |-- Poland
  |   `-- Tricity
  `-- US
      `-- California

  4 directories, 0 files

To list all of the places visited, both during private and business trips, run::

  $ tree -a -L 2 mnt/places/
  mnt/places/
  |-- Poland
  |   |-- @travels
  |   |-- Krakow
  |   |-- Tricity
  |   `-- Warsaw
  `-- US
      |-- @travels
      |-- California
      |-- Dallas
      |-- NYC
      |-- Texas
      `-- Zanzibar

  12 directories, 0 files


Example 3
~~~~~~~~~

Lets use yet another directory tree::

  $ tree -a /home/user/storage/categorization_tests/categorization-test-03/economy
  /home/user/storage/categorization_tests/categorization-test-03/economy
  |-- @market
  |   `-- stock-exchange_Warsaw-Stock-Exchange
  |       `-- GPW_description.pdf
  `-- @market_stock-exchange
      `-- Warsaw-Stock-Exchange
          `-- GPW_description.pdf

  4 directories, 2 files

After mounting with ``--only-subcontainers`` flag, you will get the following mountpoints::

  $ ls -la mnt
  total 8
  dr-xr-xr-x 1 user user    0 Jan  1  1970 ./
  drwxr-xr-x 1 user user 4096 Mar 10 11:51 ../
  dr-xr-xr-x 1 user user    0 Jan  1  1970 .backends/
  dr-xr-xr-x 1 user user    0 Jan  1  1970 .users/
  dr-xr-xr-x 1 user user    0 Jan  1  1970 .uuid/
  dr-xr-xr-x 1 user user    0 Jan  1  1970 market/

  $ tree -a mnt/market/
  mnt/market/
  `-- stock-exchange
      `-- Warsaw-Stock-Exchange
          `-- Warsaw-Stock-Exchange
              |-- GPW_description.wl_4.pdf
              `-- GPW_description.wl_5.pdf

  3 directories, 2 files

Note that Wildland autorenamed all ``GPW_description.pdf`` files to be able to place them in the
same category path.

To list all mounted containers, including 4 subcontainers, run::

  $ wl status --with-subcontainers
  Mounted containers:

  /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/.backends/503a1ccc-0265-37a1-8bfa-a2da2b553047/503a1ccc-0265-37a1-8bfa-a2da2b553047
    storage: delegate
    paths:
      /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/.backends/503a1ccc-0265-37a1-8bfa-a2da2b553047/503a1ccc-0265-37a1-8bfa-a2da2b553047
      /.backends/503a1ccc-0265-37a1-8bfa-a2da2b553047/503a1ccc-0265-37a1-8bfa-a2da2b553047
      /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/.uuid/503a1ccc-0265-37a1-8bfa-a2da2b553047
      /.uuid/503a1ccc-0265-37a1-8bfa-a2da2b553047
      /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/market/stock-exchange/Warsaw-Stock-Exchange
      /market/stock-exchange/Warsaw-Stock-Exchange
    subcontainer-of: 0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963:/.uuid/6b4afcc0-07e2-48fc-b741-0c3204d2e105

  /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/.backends/c7c98283-4124-3673-9edd-7b4a6b2be944/c7c98283-4124-3673-9edd-7b4a6b2be944
    storage: delegate
    paths:
      /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/.backends/c7c98283-4124-3673-9edd-7b4a6b2be944/c7c98283-4124-3673-9edd-7b4a6b2be944
      /.backends/c7c98283-4124-3673-9edd-7b4a6b2be944/c7c98283-4124-3673-9edd-7b4a6b2be944
      /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/.uuid/c7c98283-4124-3673-9edd-7b4a6b2be944
      /.uuid/c7c98283-4124-3673-9edd-7b4a6b2be944
      /.users/0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963/market/stock-exchange/Warsaw-Stock-Exchange
      /market/stock-exchange/Warsaw-Stock-Exchange
    subcontainer-of: 0xd7032b69d84acd834397bd336f225f46fabe6c22703380089c42987831acc963:/.uuid/6b4afcc0-07e2-48fc-b741-0c3204d2e105
