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
Wildland storage backend exposing Jira issues
"""

import uuid
from functools import partial
from pathlib import PurePosixPath
from typing import List, Tuple

import click

from wildland.container import ContainerStub
from wildland.log import get_logger
from wildland.manifest.schema import Schema
from wildland.storage_backends.base import StorageBackend
from wildland.storage_backends.generated import GeneratedStorageMixin, DirEntry, FuncDirEntry
from .jira_client import CompactIssue, JiraClient
from .jira_file_entry import JiraFileEntry

logger = get_logger('JiraBackend')
DEFAULT_ISSUES_LIMIT = 1000


class JiraStorageBackend(GeneratedStorageMixin, StorageBackend):
    """
    A read-only storage backend for Jira issues
    """

    TYPE = 'jira'

    SCHEMA = Schema({
        "title": "Storage manifest (Jira)",
        "type": "object",
        "required": ["workspace_url"],
        "properties": {
            "workspace_url": {
                "$ref": "/schemas/types.json#http-url",
                "description": "address of the v2 REST endpoint of your Jira Work Management "
                               "Cloud site"
            },
            "username": {
                "type": "string",
                "description": "(optional) the Jira username"
            },
            "personal_token": {
                "type": "string",
                "description": "(optional) personal access token generated by Jira"
            },
            "project_name": {
                "type": "array",
                "items": {
                    "type": "string"
                },
                "description": "(optional) (multiple) names of projects within your Jira Work "
                               "Management Cloud site."
            },
            "limit": {
                "type": "integer",
                "description": f"(optional) (default: {DEFAULT_ISSUES_LIMIT}) maximum amount of "
                               f"issues to be fetched starting from the most recently updated. "
            }
        }
    })

    def __init__(self, **kwds):
        super().__init__(**kwds)
        self.read_only = True
        self.client = JiraClient(
            username=self.params.get('username'),
            project_names=self.params.get('project_name'),
            personal_token=self.params.get('personal_token'),
            site_url=self.params['workspace_url'],
            limit=self.params['limit']
        )
        self.all_issues: List[CompactIssue] = []

    def mount(self) -> None:
        """
        Initiate a connection to Jira
        """
        self.all_issues = self.client.get_issues()

    def get_root(self) -> DirEntry:
        """
        Returns a function based directory
        """

        return FuncDirEntry('.', self._root)

    def _root(self):
        """
        A helper to get_root(); returns directories representing issues
        """
        for issue in self.all_issues:
            yield FuncDirEntry(self._id_issue(issue), partial(self._issue_content, issue))

    def _issue_content(self, issue: CompactIssue):
        yield JiraFileEntry(issue, self.client)

    @property
    def can_have_children(self) -> bool:
        return True

    def get_children(self, client=None, query_path: PurePosixPath = PurePosixPath('*'),
                     paths_only: bool = False):
        """
        Returns a list of categorized subcontainers for issues
        """
        logger.debug('creating subcontainers for the issues')
        assert isinstance(self.all_issues, list)

        for issue in self.all_issues:
            yield self._make_issue_container(issue, paths_only)

        logger.debug('subcontainers successfully created')

    @classmethod
    def _get_issue_categories(cls, issue: CompactIssue) -> List[str]:
        """
        Provides a list of categories the issue will appear under.
        As of right now, the main category patterns are:
        - /timeline/YYYY/MM/DD
        - /labels/ISSUE_NAME (separate category for each of the issue's labels)
        - /projects/PROJECT_NAME
        - /statuses/STATUS_NAME
        """
        paths = []
        to_return = []

        # date
        date = issue.updated_at
        paths.append(PurePosixPath('/timeline') /
                     PurePosixPath('%04d' % date.year) /
                     PurePosixPath('%02d' % date.month) /
                     PurePosixPath('%02d' % date.day))
        # status
        paths.append(PurePosixPath('/statuses') / PurePosixPath(str(issue.status)))

        # labels
        if issue.labels:
            for label in issue.labels:
                to_append = PurePosixPath('/labels')
                for part in label.split('::'):
                    to_append = to_append / PurePosixPath(part)
                paths.append(to_append)

        # project_name
        paths.append(PurePosixPath('/projects') /
                     PurePosixPath(f'{issue.project_name}'))

        for path in paths:
            to_return.append(str(path))

        return to_return

    def _id_issue(self, issue: CompactIssue) -> str:
        """
        Generates an uuid necessary in order to create the path for the subcontainers
        """
        return str(uuid.uuid3(uuid.UUID(self.backend_id), str(issue.id)))

    def _make_issue_container(self, issue: CompactIssue,
                              paths_only: bool) -> Tuple[PurePosixPath, ContainerStub]:
        """
        Creates a separate subcontainer for each of the issues fetched from the server
        """
        issue_uuid = self._id_issue(issue)
        paths = [f'/.uuid/{issue_uuid}']
        categories = self._get_issue_categories(issue)
        subcontainer_path = '/' + issue_uuid
        if not paths_only:
            return PurePosixPath(subcontainer_path), ContainerStub({
                'paths': paths,
                'title': issue.title,
                'categories': categories,
                'backends': {'storage': [{
                    'type': 'delegate',
                    'reference-container': 'wildland:@default:@parent-container:',
                    'subdirectory': subcontainer_path
                }]}
            })
        return PurePosixPath(subcontainer_path)

    @classmethod
    def cli_options(cls):
        return [
            click.Option(
                ['--workspace-url'], required=True,
                help='address of the v2 REST endpoint of your Jira Work Management Cloud site'),
            click.Option(
                ['--username'], required=False,
                help='(optional) Jira username'),
            click.Option(
                ['--personal-token'], required=False,
                help='(optional) personal access token generated for your Attlassian Account'),
            click.Option(
                ['--project-name'], required=False, multiple=True,
                help='(optional) (multiple) Jira projects names'),
            click.Option(
                ['--limit'], required=False, default=DEFAULT_ISSUES_LIMIT,
                help=f'(optional) (default: {DEFAULT_ISSUES_LIMIT}) maximum amount of issues to '
                     f'be fetched starting from the most recently updated')
        ]

    @classmethod
    def cli_create(cls, data):
        if bool(data['personal_token']) ^ bool(data['username']):
            raise TypeError('Only one of [token, user] provided. Expected either none or both.')
        return {
            'workspace_url': data['workspace_url'],
            'username': data['username'],
            'personal_token': data['personal_token'],
            'project_name': list(data['project_name']),
            'limit': data['limit'],
        }
