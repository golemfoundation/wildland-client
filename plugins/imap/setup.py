# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
#                    Piotr K. Isajew <piotr@wildland.io>
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

from setuptools import setup, find_packages

setup(
    name="wildland-imap",
    version="0.1",
    packages=find_packages(exclude=['tests', '*.tests']),
    entry_points={
        'wildland.storage_backends': [
            'imap = wildland_imap.backend:ImapStorageBackend',
        ]
   }
)
