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
A Graphql based backend meant to enhance the performance of the REST based,
initial version of the GitLab backend
"""

# pylint: disable=too-many-instance-attributes
# pylint: disable=line-too-long
from typing import List, Optional
from dataclasses import dataclass
from datetime import datetime

import requests

from wildland.log import get_logger

logger = get_logger('GitlabQLClient')


@dataclass(frozen=True)
class CompactIssue:
    """
    Dataclass created for storing necessary bits of information
    extracted from the fetched issues
    """
    milestone_title: Optional[str]
    epic_title: Optional[str]
    project_name: str
    title: str
    iid: int
    updated_at: datetime
    labels: List[str]
    ident: str
    closed: bool
    author: str


class GitlabClient:
    """
    Client implementation;
    Used for communicating with the GitLab server
    """

    def __init__(self, personal_token: str, project_path: Optional[str]):
        bearer = f'Bearer {personal_token}'
        self.headers = {"Authorization": bearer}
        self.project_path: Optional[str] = project_path

    def run_query(self, query: str):
        """
        A simple method that performs queries passed to it and returns a
        response from the server.
        """
        logger.debug('Querying the GitLab server')
        request = requests.post('https://gitlab.com/api/graphql', json={'query': query},
                                headers=self.headers)
        if request.status_code == 200:
            return request.json()

        raise Exception(
            "Query failed to run by returning code of {}. {}".format(request.status_code, query))

    def overwrite_issues(self, full_path: str, tmp_cursor: str):
        """
        This method is necessary to fully retrieve data about projects
        with more than 100 issues.
        """
        query = """query {
                    project(fullPath: "%s") {
                        name
                        issues(first: 100, after: "%s") {
                            nodes{
                                id
                                iid
                                labels(first:100){
                                    nodes{
                                        title
                                    }
                                }
                                milestone{
                                    title
                                }
                                epic{
                                    title
                                }
                                author {
                                    username
                                }
                                title
                                updatedAt
                                closedAt
                            }
                            pageInfo{
                                hasNextPage
                                endCursor
                            }
                        }
                    }
                }""" % (full_path, tmp_cursor)
        response = self.run_query(query)
        return response['data']['project']['issues']

    def create_issue_list(self, project_list: List[dict]) -> List[CompactIssue]:
        """
        Transforms the issues retrieved from the server into a list of
        compact issues (instances of the CompactIssue dataclass)
        """
        to_return = []
        for project in project_list:
            project_name = str(project['name'])
            project_issues = project['issues']
            next_page = True

            while next_page:
                assert project_issues is not None
                for issue in project_issues['nodes']:
                    labels = []
                    milestone_dict = issue.get('milestone') or {}
                    m_title = milestone_dict.get('title')
                    epic_dict = issue.get('epic') or {}
                    e_title = epic_dict.get('title')
                    update = datetime.fromisoformat((issue['updatedAt']).replace('Z', '+00:00'))
                    closed = bool(issue['closedAt'])
                    for label in issue['labels']['nodes']:
                        labels.append(label['title'])

                    to_return.append(CompactIssue(
                        milestone_title=m_title,
                        epic_title=e_title,
                        closed=closed,
                        author=issue['author']['username'],
                        project_name=project_name,
                        title=issue['title'],
                        iid=issue['iid'],
                        updated_at=update,
                        labels=labels,
                        ident=issue['id'])
                    )

                next_page = project_issues['pageInfo']['hasNextPage']
                if next_page:
                    project_issues = self.overwrite_issues(
                        str(project['fullPath']), project_issues['pageInfo']['endCursor'])

        return to_return

    def get_compact_issues(self) -> List[CompactIssue]:
        """
        Fetches a list of project issues from the server
        """
        tmp_projects = []
        to_return = []
        logger.debug('fetching a list of issues from the GitLab server')

        tmp_cursor = ' '
        next_page = True

        while next_page:
            issue_query = """query {
                projects(membership: true, first: 100, after: "%s") {
                    nodes {
                        fullPath
                        name
                        issues(first: 100, after: "") {
                            nodes{
                                id
                                iid
                                labels(first:100){
                                    nodes{
                                        title
                                    }
                                }
                                milestone{
                                    title
                                }
                                epic {
                                title
                                }
                                title
                                updatedAt
                                closedAt
                                author {
                                    username
                                }
                            }
                            pageInfo{
                                hasNextPage
                                endCursor
                            }
                        }
                    }
                    pageInfo {
                        endCursor
                        hasNextPage
                    }
                }
            }""" % tmp_cursor
            response = self.run_query(issue_query)
            nodes = response['data']['projects']['nodes']

            for node in nodes:
                tmp_projects.append(node)

            tmp_cursor = response['data']['projects']['pageInfo']['endCursor']
            next_page = response['data']['projects']['pageInfo']['hasNextPage']

        logger.debug('successfully retrieved issues from GitLab server')

        to_return = self.create_issue_list(tmp_projects)
        return to_return

    def get_project_issues(self, path: str) -> List[CompactIssue]:
        """
        Given a fullPath leading to a project, fetches all issues of said project
        and creates a list of CompactIssues from them
        """
        tmp_issues = []
        to_return = []
        tmp_cursor = ' '
        next_page = True

        while next_page:
            issue_query = """query {
                project(fullPath: "%s") {
                    name
                    issues(first: 100, after: "%s") {
                        nodes{
                            id
                            iid
                            labels(first:100){
                                nodes{
                                    title
                                }
                            }
                            milestone{
                                title
                            }
                            epic {
                                title
                            }
                            title
                            updatedAt
                            closedAt
                            author {
                                username
                            }
                        }
                        pageInfo{
                            hasNextPage
                            endCursor
                        }
                    }
                }
            }""" % (path, tmp_cursor)
            response = self.run_query(issue_query)
            name = response['data']['project']['name']
            for node in response['data']['project']['issues']['nodes']:
                tmp_issues.append(node)

            tmp_cursor = response['data']['project']['issues']['pageInfo']['endCursor']
            next_page = response['data']['project']['issues']['pageInfo']['hasNextPage']

        logger.debug('successfully retrieved issues from GitLab server')

        for issue in tmp_issues:
            labels = []
            if issue['milestone']:
                m_title = issue['milestone']['title']
            else:
                m_title = None

            closed = bool(issue['closedAt'])

            if issue['epic']:
                e_title = issue['epic']['title']
            else:
                e_title = None

            update = datetime.fromisoformat((issue['updatedAt']).replace('Z', '+00:00'))
            for label in issue['labels']['nodes']:
                labels.append(label['title'])

            to_return.append(CompactIssue(milestone_title=m_title,
                                          epic_title=e_title,
                                          closed=closed,
                                          author=issue['author']['username'],
                                          project_name=name,
                                          title=issue['title'],
                                          iid=issue['iid'],
                                          updated_at=update,
                                          labels=labels,
                                          ident=issue['id']))

        return to_return

    def get_issue_description(self, issue: CompactIssue) -> str:
        """
        Fetches a description of a single issue from the server
        """
        logger.debug('retrieveing the issue description:')

        description_query = """query {
            issue(id: "%s") {
                description
            }
        }""" % issue.ident
        response = self.run_query(description_query)

        return str(response['data']['issue']['description'])
