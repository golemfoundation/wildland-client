Contributing
============

Wildland is an Open Source project, therefore community contribution plays a key role in its life
cycle. If you wish to contribute, please see all of the requirements listed below.


Ways to contribute
------------------

Want to contribute to Wildland? That is great! There are a few ways you can contribute:

#. Test Wildland and share any bugs, thoughts, new use cases and ideas with us by creating a new issue on `Wildland GitLab`_.
#. Pick any unassigned issue from `Wildland Gitlab`_ and try to resolve it.
#. Implement a plugin for a new type of storage.
#. Expand or improve Wildland documentation.
#. Start building your Wildland forest and share it with your friends.

To add any code or documentation to the Wildland repository, you need to fork the project, `create`_
a feature branch, do some work on it and run all available tests. If all of the tests pass
successfully, you can open a new merge request that will be reviewed by Wildland's core development
team. You can expect that you will need to iteratively address all of the code review comments you
will get. When there will be no more review comments, your branch will be merged into the
``master``. In this very moment you will officially become Wildland's contributor.

.. _Wildland GitLab: https://gitlab.com/wildland/
.. _create: https://docs.gitlab.com/ee/user/project/merge_requests/creating_merge_requests.html


Coding Style Guide
------------------

As a rule of thumb: look around and stick to the coding conventions that dominate the code. Wildland
is mostly written in Python 3 with some tests and scripts written in Bash.


Python
~~~~~~

For Python code, follow `PEP-8`_ style guide. There may be exceptions to the rules imposed by PEP-8,
which are defined in `.pylintrc`_ configuration file. One notable example is the limit to 100
characters for all lines instead of the maximum of 79 and 72 characters for code and comments,
respectively.

To ensure you are following the coding conventions, run `pylint`_ linter with the `.pylintrc`_
configuration file you can find in the Wildland repository. To make sure your code is accepted by
the GitLab CI/CD pipeline, run:

.. code-block:: console

   cd ci
   docker-compose build
   docker-compose run wildland-client-ci ./ci/ci-lint

If after running the above commands you see:

.. code-block:: console

   Your code has been rated at 10.00/10

you are ready to open a `merge request`_.

.. _PEP-8: https://www.python.org/dev/peps/pep-0008/
.. _.pylintrc: http://pylint.pycqa.org/en/latest/user_guide/run.html?highlight=.pylintrc#command-line-options
.. _pylint: https://www.pylint.org/
.. _merge request: https://docs.gitlab.com/ee/user/project/merge_requests/


Bash
~~~~

We don't use any linters for Bash, but in the future we may want to use `shellcheck`_ so you can
stick to their rules. Alternatively, follow the `Google Shell Style Guide`_.

.. _shellcheck: https://github.com/koalaman/shellcheck
.. _Google Shell Style Guide: https://google.github.io/styleguide/shellguide.html


Documentation
-------------

Wildland documentation consists of:

#. Python Documentation Strings (a.k.a. `docstrings`_) described in `PEP-257`_,
#. Manual pages (a.k.a. manpages) formatted with `reStructuredText`_ saved in ``Documentation/*.rst`` files.

To convert ``*.rst`` documentation into HTML, PDF or any other format supported by `Sphinx`_, run:

.. code-block:: console

   cd ci
   docker-compose build
   docker-compose run wildland-client-ci ./ci/ci-docs

Alternatively you can generate docs without using Docker:

.. code-block:: console

   make env
   . ./env/bin/activate
   cd Documentation/
   make html

You should add docstrings to all of the public methods, classes and modules.

.. _reStructuredText: https://en.wikipedia.org/wiki/ReStructuredText
.. _Sphinx: https://en.wikipedia.org/wiki/Sphinx_(documentation_generator)
.. _docstrings: https://www.python.org/dev/peps/pep-0008/#documentation-strings
.. _PEP-257: https://www.python.org/dev/peps/pep-0257/


Commit messages
---------------

Keep your git history clean before opening merge request. When you commit your code, follow `good
practices`_, in particular:
- explain the reason for the change,
- refer to related GitLab tickets (e.g. `fixes #100`),
- make it searchable: if your commit fixes a bug, you can mention error message that inspired the change,
- don't just explain _what_ you've changed, but also _why_.

.. _good practices: https://dhwthompson.com/2019/my-favourite-git-commit
