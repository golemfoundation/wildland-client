# Wildland Project
#
# Copyright (C) 2021 Golem Foundation
#
# Authors:
#                 Dominik Gonciarz <dominik.gonciarz@besidethepark.com>
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
A class to represent Jira issue as a File
"""

import stat
from datetime import datetime

from wildland.storage_backends.base import Attr, File
from wildland.storage_backends.generated import FileEntry, StaticFile
from .jira_client import CompactIssue, JiraClient


class JiraFileEntry(FileEntry):
    """
    A slightly modified version of the StaticFileEntry class in the .generated module.
    """

    def __init__(self, issue: CompactIssue, client: JiraClient):
        super().__init__(f'{issue.title}.md')
        self.issue = issue
        self.client = client

        self.attr = Attr(
            size=len(str(self.issue.description).encode('utf-8')),
            timestamp=int(datetime.timestamp(issue.updated_at)),
            mode=stat.S_IFREG | 0o444
        )

    def getattr(self) -> Attr:
        return self.attr

    def open(self, flags: int) -> File:
        return StaticFile((str(self.issue.description)).encode('utf-8'), self.attr)
