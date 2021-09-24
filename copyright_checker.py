# Wildland Project
#
# Copyright (C) 2021 Golem Foundation
#
# Authors:
#                    Aleksander Kapera <aleksander.kapera@besidethepark.com>
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
Custom checker extension for pylint. Checks if file has correctly formatted copyright
header on the top of the file.

Provides disable keywords which include:
* copyright-violation = doesn't check for copyright notice at all
* copyright-formatting = doesn't check if copyright is correctly formatted only if it exists
* copyright-author-formatting = ignores if a list of authors is incorrectly formatted
"""

import re
from io import BufferedReader

from pylint.interfaces import IRawChecker
from pylint.checkers import BaseChecker


class CopyrightChecker(BaseChecker):
    __implements__ = IRawChecker

    name = 'copyright-checker'

    COPYRIGHT_VIOLATION = 'copyright-violation'
    COPYRIGHT_FORMATTING = 'copyright-formatting'
    COPYRIGHT_AUTHOR_FORMATTING = 'copyright-author-formatting'

    msgs = {
        'C5001': ('No copyright message provided',
                  COPYRIGHT_VIOLATION,
                  'Each .py file should contain copyright message at the top'),
        'C5002': ('Incorrect copyright message format at line: "%s". Expected format: "%s"',
                  COPYRIGHT_FORMATTING,
                  'Correct formatting can be found in copyright_template file'),
        'C5003': ('Incorrect copyright author format at line: "%s". Example of correct author '
                  'line: #\t\tJoe Doe <joe@doe.com>',
                  COPYRIGHT_AUTHOR_FORMATTING,
                  'Correct formatting can be found in copyright_template file'),
    }
    options = ()

    priority = -1

    def process_module(self, node):
        """
        If node doesn't contain disable comment, check if file has correctly formatted copyright
        notice.
        """

        # ignore __init__.py files, it cannot be implemented in .pylintrc file because disabling
        # checks for that file doesn't work
        if re.search(r'__init__\.py$', node.file) is None:
            with node.stream() as file_stream, open('copyright_template', 'r') as template_stream:
                file_index, template_index = 0, 0
                template_lines = template_stream.readlines()
                file_line = file_stream.readline().decode('utf-8')
                pylint_disable_regex = f'# pylint:.*disable=.*({self.COPYRIGHT_VIOLATION}|'\
                                       f'{self.COPYRIGHT_FORMATTING}|'\
                                       f'{self.COPYRIGHT_AUTHOR_FORMATTING})'

                if re.match(pylint_disable_regex, file_line):
                    # contains copyright disable comment, skip check
                    return
                if file_line.strip() == '#!/usr/bin/env python3':
                    file_line = file_stream.readline().decode('utf-8')
                    file_index += 1

                while template_index < len(template_lines):
                    template_line = template_lines[template_index]

                    if template_line.strip() == '# Authors:':
                        if file_line.strip() != '# Authors:':
                            # copyright header doesn't have any authors, skip check
                            template_index += 3
                            template_line = template_lines[template_index]
                        else:
                            template_index += 1
                            file_index, template_index = self.check_authors(file_stream,
                                                                            template_lines,
                                                                            file_index,
                                                                            template_index)

                    if template_line.strip() != '# Authors:':
                        matched = re.match(template_line, file_line)
                        args = file_line, template_line.strip()
                        if matched is None:
                            if template_index != 0:
                                # copyright notice is incorrectly formatted
                                self.add_message(self.COPYRIGHT_FORMATTING,
                                                 line=file_index,
                                                 args=args)
                            else:
                                # file doesn't have copyright notice
                                self.add_message(self.COPYRIGHT_VIOLATION, line=0)
                                break

                    file_line = file_stream.readline().decode('utf-8')
                    file_index += 1
                    template_index += 1

    def check_authors(self, file_stream: BufferedReader, template_lines: [str], file_index: int,
                      template_index: int):
        """
        Check if 'authors' section of a copyright notice is correctly formatted.
        """
        print(type(file_stream))
        print(type(template_lines))
        print(type(file_index))
        print(type(template_index))
        file_line = file_stream.readline().decode('utf-8')
        template_line = template_lines[template_index]
        while "#" != file_line.strip():
            if re.match(template_line, file_line) is None:
                self.add_message(self.COPYRIGHT_AUTHOR_FORMATTING, line=file_index, args=file_line)

            file_index += 1
            file_line = file_stream.readline().decode('utf-8')

        return file_index, template_index + 1


def register(linter):
    linter.register_checker(CopyrightChecker(linter))
