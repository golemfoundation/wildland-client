#!/usr/bin/env python3
# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
#                    Patryk Bęza <patryk@wildland.io>
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
Performance profiler diff tool for comparing Pyinstrument profiler outputs
"""

import argparse
import logging
import json

from collections import deque
from copy import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from .profiler_diff import (
    BaseFunctionProfilerStats,
    BaseFunctionProfilerStatsDiff,
    BaseProgramProfilerStats,
    BaseProgramProfilerStatsDiff,
    percentage_diff
)


logger = logging.getLogger('pyinstrument-profile-diff')


@dataclass
class PyinstrumentFunctionProfilerStats(BaseFunctionProfilerStats):
    """
    Pyinstrument-specific variant of :class:`BaseFunctionProfilerStats`.
    """

    # Mapping from names of the functions called by this function to its stats
    children: Dict[str, 'PyinstrumentFunctionProfilerStats']
    await_time: float
    file_path_short: str
    file_path: str
    line_no: int
    is_application_code: bool
    group_id: Optional[str]

    def get_children(self) -> Iterable['PyinstrumentFunctionProfilerStats']:
        return self.children.values()

    @classmethod
    def from_json(cls, profiler_json_obj: Dict[str, Any]) -> 'PyinstrumentFunctionProfilerStats':
        """
        Create :class:`PyinstrumentFunctionProfilerStats` instance from given dictionary
        corresponding to the JSON Pyinstrument output file.
        """
        obj = profiler_json_obj
        return cls(
            function_name=obj['function'],
            cumulative_time=obj['time'],
            children={c['function']: cls.from_json(c) for c in obj['children']},
            await_time=obj['await_time'],
            file_path_short=obj['file_path_short'],
            file_path=obj['file_path'],
            line_no=obj['line_no'],
            is_application_code=obj['is_application_code'],
            group_id=obj.get('group_id')
        )


@dataclass
class PyinstrumentFunctionProfilerStatsDiff(BaseFunctionProfilerStatsDiff):
    """
    Pyinstrument-specific variant of :class:`BaseFunctionProfilerStatsDiff`.
    """

    # Mapping from names of the functions called by this function to its stats
    children: Dict[str, 'PyinstrumentFunctionProfilerStatsDiff']

    # Stats corresponding to the 1st run of the profiler on the function
    old_stats: Optional[PyinstrumentFunctionProfilerStats]

    # Stats corresponding to the 2nd run of the profiler on the function
    new_stats: Optional[PyinstrumentFunctionProfilerStats]

    def get_await_time_diff(self) -> float:
        """
        Difference in function await time between profiler runs.
        """
        if self.old_stats and self.new_stats:
            return self.new_stats.await_time - self.old_stats.await_time
        return float('NaN')

    @classmethod
    def diff_stats(cls,
            old_stats: PyinstrumentFunctionProfilerStats,
            new_stats: PyinstrumentFunctionProfilerStats) \
                -> Optional['PyinstrumentFunctionProfilerStatsDiff']:
        """
        Create a diff-tree between two profiler runs stats by running BFS traversal on trees
        corresponding to the given arguments.
        """

        if old_stats.function_name != new_stats.function_name:
            logger.warning('Unable to compare different function calls (%s vs %s). Aborting diff.',
                           old_stats.function_name, new_stats.function_name)
            return None

        root = cls(old_stats=old_stats, new_stats=new_stats, children={})
        parent = root
        queue = deque([parent])

        while queue:
            parent = queue.popleft()

            assert parent.old_stats and parent.new_stats
            new_only_children = copy(parent.new_stats.children)  # some of them will be removed

            for fun_name, old_child in parent.old_stats.children.items():
                # if the function present in both trees
                if fun_name in new_only_children:
                    new_child = new_only_children[fun_name]
                    stats_diff = cls(old_stats=old_child, new_stats=new_child, children={})
                    queue.append(stats_diff)
                    del new_only_children[fun_name]
                else:  # present only in the old tree
                    stats_diff = cls(old_stats=old_child, new_stats=None, children={})
                assert stats_diff
                assert fun_name not in parent.children
                parent.children[fun_name] = stats_diff

            for fun_name, new_child in new_only_children.items():
                stats_diff = cls(old_stats=None, new_stats=new_child, children={})
                parent.children[fun_name] = stats_diff

        return root

    def to_str(self, include_children: bool=False) -> str:
        """
        Create and return string representation of the object.
        """
        array_repr = [
            f'function_name={self.get_function_name()}',
            f'cumulative_time_diff={self.get_cumulative_time_diff()}',
            f'cumulative_time_percent_diff={self.get_cumulative_time_percent_diff()}',
            f'total_time_percent_diff={self.get_total_time_percent_diff()}',
            f'total_time_diff={self.get_total_time_diff()}',
            f'total_time_percent_diff={self.get_total_time_percent_diff()}',
            f'await_time_diff={self.get_await_time_diff()}',
            f'function_state={self.get_function_state()}',
            'children=[' + ', '.join([str(c) for c in self.children.values()]) + ']'
        ]
        if include_children:
            array_repr += [
                f'old_stats={self.old_stats}',
                f'new_stats={self.new_stats}'
            ]
        str_repr = self.__class__.__name__ + '(' + ', '.join(array_repr) + ')'
        return str_repr

    def __repr__(self) -> str:
        return self.to_str()

    def __str__(self) -> str:
        return self.to_str()


@dataclass
class PyinstrumentProgramProfilerStats(BaseProgramProfilerStats):
    """
    Pyinstrument-specific variant of :class:`BaseProgramProfilerStats`.
    """

    # Detailed pyinstrument-specific profiler stats of the function call tree
    function_stats: PyinstrumentFunctionProfilerStats
    start_time: float
    sample_count: int
    program_cmd: str
    cpu_time: float

    @classmethod
    def from_json(cls, profiler_json_obj: Dict) -> 'PyinstrumentProgramProfilerStats':
        """
        Create :class:`PyinstrumentProgramProfilerStats` instance from given dictionary
        corresponding to the JSON pyinstrument output file.
        """
        obj = profiler_json_obj
        return cls(
            function_stats=PyinstrumentFunctionProfilerStats.from_json(obj['root_frame']),
            duration=obj['duration'],
            start_time=obj['start_time'],
            sample_count=obj['sample_count'],
            program_cmd=obj['program'],
            cpu_time=obj['cpu_time']
        )

    @classmethod
    def from_json_file(cls, profiler_json_output: Path) -> 'PyinstrumentProgramProfilerStats':
        """
        Create :class:`PyinstrumentProgramProfilerStats` instance from given JSON pyinstrument
        output file.
        """
        with open(profiler_json_output) as stats_file:
            json_dict = json.load(stats_file)
        return cls.from_json(json_dict)


class PyinstrumentProgramProfilerStatsDiff(BaseProgramProfilerStatsDiff):
    """
    Pyinstrument-specific :class:`BaseProfilerDiff`.
    """

    old_prog_stats: PyinstrumentProgramProfilerStats
    new_prog_stats: PyinstrumentProgramProfilerStats
    root_diff: Optional[PyinstrumentFunctionProfilerStatsDiff]

    def __init__(self,
            old_prog_stats: PyinstrumentProgramProfilerStats,
            new_prog_stats: PyinstrumentProgramProfilerStats):

        self.old_prog_stats = old_prog_stats
        self.new_prog_stats = new_prog_stats
        self.root_diff = PyinstrumentFunctionProfilerStatsDiff.diff_stats(
            old_prog_stats.function_stats,
            new_prog_stats.function_stats
        )

    def get_start_time_diff(self) -> float:
        """
        Get the difference between the times the profiler program started.
        """
        return self.new_prog_stats.start_time - self.old_prog_stats.start_time

    def get_sample_count_diff(self) -> int:
        """
        Get the difference between the number of samples in the 1st and 2nd profiler run.
        """
        return self.new_prog_stats.sample_count - self.old_prog_stats.sample_count

    def get_cpu_time_diff(self) -> float:
        """
        Get the difference between the CPU time between the 1st and 2nd run of the profiler.
        """
        return self.new_prog_stats.cpu_time - self.old_prog_stats.cpu_time

    def get_duration_diff(self) -> float:
        """
        Get the difference between the total duration of the 1st and 2nd run of the profiler.
        """
        return self.new_prog_stats.duration - self.old_prog_stats.duration

    def get_duration_percentage_diff(self) -> float:
        """
        Get the percentage difference between the total duration of the 1st and 2nd run of the
        profiler.
        """
        return percentage_diff(self.old_prog_stats.duration, self.new_prog_stats.duration)

    @classmethod
    def diff_stats_from_files(cls,
            old_profiler_json: Path,
            new_profiler_json: Path) -> 'PyinstrumentProgramProfilerStatsDiff':
        """
        Create a diff between two profiler runs represented by JSON files. Diff is represented with
        nodes represented by :class:`PyinstrumentFunctionProfilerStatsDiff`. Return ``None`` if
        given stats correspond to different functions.
        """
        old_prog_stats = PyinstrumentProgramProfilerStats.from_json_file(old_profiler_json)
        new_prog_stats = PyinstrumentProgramProfilerStats.from_json_file(new_profiler_json)
        return cls(old_prog_stats=old_prog_stats, new_prog_stats=new_prog_stats)

    def to_str(self, include_children: bool=False) -> str:
        """
        Create and return string representation of the object.
        """
        array_repr = [
            f'start_time_diff={self.get_start_time_diff()}',
            f'get_sample_count_diff={self.get_sample_count_diff()}',
            f'get_cpu_time_diff={self.get_cpu_time_diff()}',
            f'get_duration_diff={self.get_duration_diff()}',
            f'get_duration_percentage_diff={self.get_duration_percentage_diff()}',
            f'root_diff={self.root_diff}'
        ]
        if include_children:
            array_repr += [
                f'old_prog_stats={self.old_prog_stats}',
                f'new_prog_stats={self.new_prog_stats}'
            ]
        str_repr = self.__class__.__name__ + '(' + ', '.join(array_repr) + ')'
        return str_repr

    def __repr__(self) -> str:
        return self.to_str()

    def __str__(self) -> str:
        return self.to_str()


def main():
    """
    Entry point.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('old_json_path', help='Path to the JSON output file corresponding to the ' \
        'first performance profiler run (a.k.a. old one).')
    parser.add_argument('new_json_path', help='Path to the JSON output file corresponding to the ' \
        'second performance profiler run (a.k.a. new one).')

    args = parser.parse_args()
    PyinstrumentProgramProfilerStatsDiff.print_diff(args.old_json_path, args.new_json_path)


if __name__ == '__main__':
    main()
