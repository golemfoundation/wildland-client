# Wildland Project
#
# Copyright (C) 2021 Golem Foundation
#
# Authors:
#                    Marta Marczykowska-Górecka <marmarta@invisiblethingslab.com>,
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
Exceptions related to Cli module operations.
"""
from gettext import gettext
from typing import Optional, IO
import click
from click.exceptions import get_text_stderr
from ..exc import WildlandError


class CliError(WildlandError, click.ClickException):
    """
    User error during CLI command execution
    """
    def show(self, file: Optional[IO] = None) -> None:
        if file is None:
            file = get_text_stderr()

        click.secho(
            gettext("Error: {message}").format(message=self.format_message()), file=file, fg="red")
