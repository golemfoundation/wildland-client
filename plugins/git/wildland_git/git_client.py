# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
#                 Maja Kostacinska <maja@wildland.io>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Initial implementation of the git backend used to expose git repositories
as wildland containers
"""

# pylint: disable=no-member
import os
import shutil
from typing import List, Union, Optional

from git import Repo, Blob, Tree, exc

from wildland.exc import WildlandError
from wildland.log import get_logger

logger = get_logger('git-client')


class GitClient:
    """
    GitClient responsible for handling the cloned repository data
    """

    def __init__(self, repo_url: str, location: str,
                 username: Optional[str], password: Optional[str]):
        self.location = location
        self.username = username
        self.password = password
        if self.username and self.password:
            self.url = self.parse_url(repo_url)
        else:
            self.url = repo_url
        self.repo: Optional[Repo] = None

    def connect(self) -> None:
        """
        Clones the chosen repo to /tmp/git_repo/{owner}/{directory uuid} and
        creates an instance of git.Repo so that all the necessary
        information about the chosen repository can be accessed from the
        client.

        Upon mounting the storage, the previous version of the cloned repo
        (if such exists) is removed from its location so that a new,
        up to date version can be cloned.

        Because of this, the authorization with parameters (--username/--password)
        is preferred over the authorization over the prompt
        (the backend will continuously prompt for the username and password
        upon every mount/unmount of the container), but you can choose to use the
        prompt if you don't want your credentials to be shown in bash history.
        """
        # removes the current contents of the directory
        if os.path.isdir(self.location) and os.listdir(self.location):
            try:
                shutil.rmtree(self.location)
            except OSError as error:
                raise WildlandError('Cleaning the directory %s unsuccessful: %s'
                                    % (self.location, error.strerror)) from error

        try:
            os.makedirs(self.location)
        except FileExistsError:
            pass

        try:
            self.repo = Repo.clone_from(url=self.url, to_path=self.location, depth=1)
        except exc.GitCommandError:
            # TODO
            # https://gitlab.com/wildland/wildland-client/-/issues/553
            pass

    def parse_url(self, url: str) -> str:
        """
        Parses the initially provided url into one following the
        https://username:token@host.xz[:port]/path/to/repo.git so
        that the default command line authorization can be omitted.
        """
        assert self.username is not None
        assert self.password is not None
        url_parts = url.split('//')
        to_return = url_parts[0] + '//' + self.username + ':' + self.password + '@' + url_parts[1]
        return to_return

    def disconnect(self) -> None:
        """
        Clean up; used when unmounting the container
        """
        self.repo = None
        if os.listdir(self.location):
            try:
                shutil.rmtree(self.location)
            except OSError as error:
                raise WildlandError('Cleaning the directory %s unsuccessful: %s'
                                    % (self.location, error.strerror)) from error

    def list_folder(self, path_parts: List[str]) -> List[Union[Blob, Tree]]:
        """
        Lists all git objects under the specified path
        """
        assert self.repo is not None
        assert self.repo.head is not None
        initial_tree = self.repo.head.commit.tree
        to_return = []

        for part in path_parts:
            initial_tree = initial_tree[part]

        for tree in initial_tree.trees:
            to_return.append(tree)

        for blob in initial_tree.blobs:
            to_return.append(blob)

        return to_return

    def get_commit_timestamp(self):
        """
        Returns the timestamp of the repo's HEAD commit
        """
        assert self.repo is not None
        assert self.repo.head is not None
        return self.repo.head.commit.committed_date

    def get_object(self, path_parts: List[str]) -> Union[Blob, Tree]:
        """
        Returns a git object (blob/tree) found under the specified path
        """
        assert self.repo is not None
        assert self.repo.head is not None
        initial_tree = self.repo.head.commit.tree

        for part in path_parts:
            initial_tree = initial_tree[part]

        return initial_tree

    def get_file_content(self, path_parts: List[str]) -> bytes:
        """
        Returns the content of a specified file in bytes
        """
        obj = self.get_object(path_parts)
        return obj.data_stream.read()
