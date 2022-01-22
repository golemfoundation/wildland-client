# Wildland Project
#
# Copyright (C) 2022 Golem Foundation
#
# Authors:
#           Aleksandr Birukov <aleksandr.birukov@besidethepark.com>,
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
# pylint: disable=global-statement

"""
Module for initialisation of the Cleaner instance with the "click" output functions
"""

from typing import Optional
import click

from .cleaner import Cleaner

cleaner: Optional[Cleaner] = None


def get_cli_cleaner():
    """
    Return and initialize if needed a Cleaner instance with the "click" output functions.
    """
    global cleaner
    if not cleaner:
        cleaner = Cleaner(
            click.echo,
            lambda *args, **kwargs: click.secho(*args, **kwargs, fg='yellow')
        )
    return cleaner
