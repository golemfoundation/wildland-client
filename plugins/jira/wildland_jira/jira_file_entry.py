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
            size=len(self.issue.description),
            timestamp=int(datetime.timestamp(issue.updated_at)),
            mode=stat.S_IFREG | 0o444
        )

    def getattr(self) -> Attr:
        return self.attr

    def open(self, flags: int) -> File:
        return StaticFile((str(self.issue.description)).encode('utf-8'), self.attr)
