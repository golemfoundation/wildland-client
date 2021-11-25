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
Jira client wrapping functions responsible for communication with Jira API
"""
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

import dateutil.parser
import requests

from wildland.exc import WildlandError
from wildland.log import get_logger
from .utils import stringify_query_params, encode_basic_auth, encode_dict_to_jql, ParamDict

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

    def __init__(self, site_url: str, limit: int, username: Optional[str],
                 personal_token: Optional[str], project_names: Optional[List[str]] = None):
        if project_names is None:
            project_names = []
        self.headers = {}
        if username and personal_token:
            self.headers["Authorization"] = f'Basic {encode_basic_auth(username, personal_token)}'
        elif username or personal_token:
            logger.warning("Only one of [username, token] given. Authorization will be ignored.")
        self.projects_names: Optional[List[str]] = project_names
        self.url = site_url if site_url.endswith('/') else f'{site_url}/'
        self.limit = limit
        self.validate_project_names()

    def validate_project_names(self):
        """
        Validates whether Jira recognises projects with given names.
        """
        if not isinstance(self.projects_names, list) or len(self.projects_names) < 1:
            return
        all_projects = self.run_query('project', {})
        all_projects_names = map(lambda project: project['name'], all_projects)
        unmatched_names = set(self.projects_names).difference(all_projects_names)
        if len(unmatched_names) == 0:
            return
        error = 'Projects with the following names could not be found: {}.'.format(
            ', '.join(unmatched_names))
        raise WildlandError(error)

    def run_query(self, path: str, params: ParamDict):
        """
        A simple method that performs queries passed to it and returns a response from the server.
        """
        logger.debug('Querying the Jira server')
        params_str = stringify_query_params(params)

        uri = f'{self.url}{path}{params_str}'
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
                title=str(issue['fields']['summary']).replace('\n', ''),
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
        params: ParamDict = {
            'fields': ['summary', 'description', 'labels', 'project', 'updated', 'status'],
            'maxResults': 100,
            'startAt': 0,
            'jql': ''
        }

        if isinstance(self.projects_names, list) and len(self.projects_names):
            params['jql'] = encode_dict_to_jql({'project': self.projects_names})
        else:
            params['jql'] = encode_dict_to_jql(None)

        has_next_page = True
        parsed_issues: List[CompactIssue] = []
        while has_next_page and len(parsed_issues) < self.limit:
            params['startAt'] = len(parsed_issues)
            if params['maxResults'] > self.limit - len(parsed_issues):
                params['maxResults'] = self.limit - len(parsed_issues)
            response = self.run_query('search', params)
            parsed_issues.extend(self.parse_issue_list(response['issues']))
            if response.get('total') is None:
                # 'total' can be missing in cases when calculating its value is too expensive
                # https://docs.atlassian.com/software/jira/docs/api/REST/8.13.12/#pagination
                raise WildlandError(
                    'Unable to continue fetching issues because its total number is unknown. Try '
                    'with a smaller number of projects')

            has_next_page = len(parsed_issues) < response['total']

        logger.debug('Number of fetched issues: %d', len(parsed_issues))
        return parsed_issues
