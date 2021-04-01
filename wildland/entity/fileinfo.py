# Wildland Project
#
# Copyright (C) 2021 Golem Foundation
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
# pylint: disable=missing-docstring
from pathlib import Path


class FileInfo():
    def __init__(self,
                 container_path: str,
                 backend_id: str,
                 storage_owner: str,
                 storage_read_only: bool,
                 storage_id: str,
                 file_token: str = ''):
        self._params = {
            'container_path': container_path,
            'backend_id': backend_id,
            'storage_owner': storage_owner,
            'storage_read_only': storage_read_only,
            'storage_id': storage_id,
            'file_token': file_token,
        }

    def __repr__(self):
        return f'{type(self).__name__}({self._params!r})'

    @property
    def container_path(self) -> Path:
        return Path(str(self._params['container_path']))

    @property
    def backend_id(self) -> str:
        return str(self._params['backend_id'])

    @property
    def storage_owner(self) -> str:
        return str(self._params['storage_owner'])

    @property
    def storage_read_only(self) -> bool:
        return bool(self._params['storage_read_only'])

    @property
    def storage_id(self) -> str:
        return str(self._params['storage_id'])

    @property
    def file_token(self) -> str:
        return str(self._params['file_token'])
