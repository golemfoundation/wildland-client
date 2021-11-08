# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
#                       Maja Kostacinska <maja@wildland.io>
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
gitlab_client fetches the information necessary for exposing the issues
in the backend.
"""
from dataclasses import dataclass
from datetime import datetime
# pylint: disable=too-many-instance-attributes
# pylint: disable=no-member
from typing import List, Optional, Union

import gitlab
import requests
from gitlab.v4.objects.issues import ProjectIssue
from wildland.log import get_logger

logger = get_logger('GitlabClient')


@dataclass(frozen=True)
class CompactIssue:
    """
    Dataclass created for storing necessary bits of information
    extracted from the fetched issues
    """
    milestone_title: str
    project_id: Union[str, int]
    project_name: str
    title: str
    iid: int
    updated_at: datetime
    labels: List[str]
    ident: int
    issue_size: int


class GitlabClient:
    """
    Client implementation;
    Used for communicating with the GitLab server
    """

    def __init__(self, url: str, personal_token: str, project_id: Optional[Union[str, int]]):
        self.url = url
        self.personal_token = personal_token
        self.gitlab: Optional[gitlab.Gitlab] = None
        self.project_id = project_id
        self.session = requests.Session()

    def connect(self):
        """
        Creates an instance of the GitLab server necessary in order
        to obtain information about the issues
        """
        logger.debug('connecting to GitLab server')
        self.gitlab = gitlab.Gitlab(url=self.url,
                                    private_token=self.personal_token,
                                    session=self.session)

        logger.debug('connected to GitLab server')

    def disconnect(self):
        """
        Disconnects from the GitLab server
        """
        logger.debug('disconnecting from GitLab server')
        self.session.close()
        logger.debug('disconnected from GitLab server')

    def get_compact_issues(self) -> List[CompactIssue]:
        """
        Fetches the issues from the server and extracts necessary
        information from them.
        """
        tmp_issues = []
        project_names = {}
        to_return = []

        assert self.gitlab is not None
        logger.debug('fetching a list of issues from the GitLab server')
        if self.project_id:
            projects = [self.gitlab.projects.get(self.project_id)]
        else:
            # Casting RESTObject list to Project list to satisfy mypy
            projects = [gitlab.v4.objects.Project(self.gitlab.projects, i.attributes)
                        for i in self.gitlab.projects.list(membership=True)]

        for project in projects:
            tmp_issues.extend(project.issues.list(all=True, per_page=100))
            project_names[project.attributes['id']] = project.attributes['name']

        to_return = self.create_issue_list(tmp_issues, project_names)
        logger.debug('successfully retrieved issues from GitLab server')

        return to_return

    @staticmethod
    def create_issue_list(issue_list, project_names) -> List[CompactIssue]:
        """
        Transforms the issues retrieved from the server into a list of compact issues
        (instances of the CompactIssue dataclass)
        """
        to_return = []
        for issue in issue_list:
            if issue.attributes['milestone']:
                m_title = (issue.attributes['milestone']).get('title')
            else:
                m_title = None

            if issue.attributes['description']:
                size = len(issue.attributes['description'])
            else:
                size = 0

            update = datetime.fromisoformat(issue.attributes['updated_at'].replace('Z', '+00:00'))
            name = project_names.get(issue.attributes['project_id'])
            to_return.append(CompactIssue(milestone_title=m_title,
                                          project_id=issue.attributes['project_id'],
                                          project_name=name,
                                          title=issue.attributes['title'],
                                          iid=issue.attributes['iid'],
                                          updated_at=update,
                                          labels=issue.attributes['labels'],
                                          ident=issue.attributes['id'],
                                          issue_size=size))

        return to_return

    @staticmethod
    def _create_issue_content(issue: ProjectIssue) -> str:
        try:
            description = issue.attributes['description']
            description = description.replace("\n", "  \n")
            description += "  \n"
        except AttributeError:
            description = 'None'
        created_at_str = issue.attributes['created_at']
        created_at_dt: datetime = datetime.strptime(created_at_str, "%Y-%m-%dT%H:%M:%S.%fZ")
        created_at = created_at_dt.strftime("%Y-%m-%d %H:%M")
        labels = " | ".join(issue.attributes['labels'])
        if labels == "":
            labels = 'None'
        milestone = issue.attributes['milestone']
        epic_attr = issue.attributes['epic']
        if epic_attr is None:
            epic = 'None'
        else:
            epic = epic_attr['title']
        author = issue.attributes['author']['name']
        author_url = issue.attributes['author']['web_url']
        assignees_tuples = [(a['name'], a['web_url']) for a in issue.attributes['assignees']]
        assignees_strings = [f"[{at[0]}]({at[1]})" for at in assignees_tuples]
        assignees: str = " | ".join(assignees_strings)
        if assignees == "":
            assignees = 'None'
        web_url = issue.attributes['web_url']
        ref_link = issue.attributes['references']['full']

        markdown_text = f""">  \n
> created at: `{created_at}`  
> labels: `{labels}`  
> milestone: `{milestone}`  
> epic: `{epic}`  
> author: [{author}]({author_url})  
> assignees: `{assignees}`  
> web_url: [{ref_link}]({web_url})  

## description
{description}
"""
        return markdown_text

    def get_issue_description(self, issue: CompactIssue) -> str:
        """
        Fetches a description of a single issue from the server
        """
        logger.debug('retrieveing the issue description:')

        assert self.gitlab is not None
        retrieved_issue: ProjectIssue = (self.gitlab.projects.get(issue.project_id)) \
            .issues.get(issue.iid)
        return self._create_issue_content(retrieved_issue)
