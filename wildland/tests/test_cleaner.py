# Wildland Project
#
# Copyright (C) 2022 Golem Foundation
#
# Authors:
#                    Aleksandr Birukov <aleksandr.birukov@besidethepark.com>,
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

# pylint: disable=missing-docstring,redefined-outer-name

"""
Tests for cleaner
"""

from pathlib import Path

from wildland.cleaner import Cleaner


def test_cleaner_removes_files(tmpdir):
    paths = [
        Path(tmpdir / 'a.txt'),
        Path(tmpdir / 'b.txt'),
    ]
    cleaner = Cleaner()
    for path in paths:
        path.write_text('data')
        cleaner.add_path(path)

    cleaner.clean_up()

    assert not paths[0].exists()
    assert not paths[1].exists()


def test_cleaner_log_nothing_when_no_files(capfd):
    cleaner = Cleaner()
    cleaner.clean_up()
    out, err = capfd.readouterr()

    assert not out
    assert not err


def test_cleaner_log_error_and_continue(tmpdir, capfd):
    cleaner = Cleaner()
    paths = [
        Path(tmpdir / 'a.txt'),
        Path(tmpdir / 'b.txt'),
    ]
    paths[1].write_text('data')
    cleaner.add_path(paths[0])
    cleaner.add_path(paths[1])
    cleaner.clean_up()

    out, _ = capfd.readouterr()
    assert f'Can\'t remove file {paths[0]}: [Errno 2] No such file or directory' in out
    assert not paths[1].exists()
