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
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Union

import dateutil.parser
import requests

from wildland.log import get_logger
from .utils import stringify_query_params, encode_basic_auth

logger = get_logger('JiraClient')


@dataclass(frozen=True)
class CompactIssue:
    """
    Dataclass created for storing necessary bits of information
    extracted from the fetched issues
    """
    status: str
    project_name: str
    title: str
    id: int
    updated_at: datetime
    labels: List[str]
    description: str


class JiraClient:
    """
    Fetches and parses Jira issues
    """

    def __init__(self, site_url: str, username: str, personal_token: str, project_names: Optional[List[str]] = None):
        if project_names is None:
            project_names = []
        self.headers = {"Authorization": f'Basic {encode_basic_auth(username, personal_token)}'}
        self.projects_names: Optional[List[str]] = project_names
        self.url = site_url if site_url.endswith('/') else f'{site_url}/'

    def run_query(self, path: str, params: Dict[str, Union[str, List[str]]]):
        """
        A simple method that performs queries passed to it and returns a response from the server.
        """
        logger.debug('Querying the Jira server')
        params = stringify_query_params(params)

        uri = f'{self.url}{path}{params}'
        request = requests.get(uri, headers=self.headers)
        if request.status_code == 200:
            return request.json()

        raise Exception(
            "Query failed to run by returning code of {}. {}".format(request.status_code, uri))

    @staticmethod
    def parse_issue_list(issue_list) -> List[CompactIssue]:
        """
        Transforms the issues retrieved from the server into a list of compact issues
        (instances of the CompactIssue dataclass)
        """
        to_return = list()
        for issue in issue_list:
            to_return.append(CompactIssue(
                title=issue['fields']['summary'],
                id=issue['id'],
                updated_at=dateutil.parser.parse(issue['fields']['updated']),
                labels=issue['fields']['labels'],
                status=issue['fields']['status']['name'],
                project_name=issue['fields']['project']['name'],
                description=issue['fields']['description'] or ''
            ))
        return to_return

    def get_issues(self) -> List[CompactIssue]:
        """
        Fetches all issues in given workspace.
        """
        params = {
            'fields': ['summary', 'description', 'labels', 'project', 'updated', 'status'],
            'orderBy': '+summary',
            'maxResults': 100,
        }

        if len(self.projects_names):
            params['jql'] = f'projects={urllib.parse.quote(",".join(self.projects_names))}'

        has_next_page = True
        parsed_issues = []
        while has_next_page:
            params['startAt'] = len(parsed_issues)
            response = self.run_query('search', params)
            parsed_issues.extend(self.parse_issue_list(response['issues']))
            # TODO: 'total' can be missing in cases when calculating its value is too expensive
            has_next_page = len(parsed_issues) < response['total']

        logger.warn(f'Number of fetched items: {len(parsed_issues)}')
        return parsed_issues
