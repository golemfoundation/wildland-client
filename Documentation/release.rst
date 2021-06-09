Release checklist
=================

Things to do when releasing new wildland-client version:

1. Verify that all tutorials from `wildland-tutorials` repo are still accurate and works.
2. Update version in `wildland/__init__.py`, in a separate commit and a commit message "version X.Y.Z".
3. Create a signed tag in form ``vX.Y.Z`` and message "version X.Y.Z".
4. Push both updated ``master`` branch and the new tag to gitlab.com. Push the same to the ``stable`` branch too.
