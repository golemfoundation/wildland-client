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
Base classes of the performance profiler diff tool for comparing profiler outputs
"""

import abc

from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Iterable, Optional

from wildland.log import get_logger

logger = get_logger('profiler-diff')


@dataclass
class _BaseFunctionProfilerStats:
    """
    This class a workaround for mypy issue with abstract dataclasses:
    https://github.com/python/mypy/issues/5374
    """

    # Name of the function being ran under performance profiler
    function_name: str

    # Time spent on executing `function_name` including its children
    cumulative_time: float


class BaseFunctionProfilerStats(_BaseFunctionProfilerStats, abc.ABC):
    """
    Base class for keeping track of the function call profiler stats.
    """

    @abc.abstractmethod
    def get_children(self) -> Iterable['BaseFunctionProfilerStats']:
        """
        Get the stats of the functions called by the function corresponding to this object.
        """
        raise NotImplementedError

    def get_cumulative_time(self):
        """
        Get the cumulative execution time, which is the execution time of the function, including
        the time spent executing the functions called by the function corresponding to this object.
        """
        return self.cumulative_time

    def get_total_time(self):
        """
        Get the total execution time, which is the execution time of the function, excluding the
        time spent executing the functions called by the function corresponding to this object.
        """
        return self.cumulative_time - sum(c.cumulative_time for c in self.get_children())


@dataclass
class BaseFunctionProfilerStatsDiff:
    """
    Class for keeping track a diff between profiler stats of a single function.
    """

    class State(Enum):
        """
        Indicates whether particular function was called in both profiler runs or just one of them
        (old or new). Having this state helps with determining whether stats can be compared between
        profiler runs.
        """
        NEW = auto()
        OLD = auto()
        COMMON = auto()

    # Stats corresponding to the 1st run of the profiler on the function
    old_stats: Optional[BaseFunctionProfilerStats]

    # Stats corresponding to the 2nd run of the profiler on the function
    new_stats: Optional[BaseFunctionProfilerStats]

    def get_function_name(self) -> str:
        """
        Get name of the function whose profiler stats are diff-ed.
        """
        if self.old_stats:
            if self.new_stats:
                assert self.new_stats.function_name == self.old_stats.function_name
            return self.old_stats.function_name

        assert self.new_stats
        return self.new_stats.function_name

    def get_cumulative_time_diff(self) -> float:
        """
        Difference in function cumulative execution time (i.e. including children) between profiler
        runs.
        """
        if self.old_stats and self.new_stats:
            return self.new_stats.get_cumulative_time() - self.old_stats.get_cumulative_time()
        return float('NaN')

    def get_total_time_diff(self) -> float:
        """
        Difference in function total execution time (i.e. excluding children) between profiler runs.
        """
        if self.old_stats and self.new_stats:
            return self.new_stats.get_total_time() - self.old_stats.get_total_time()
        return float('NaN')

    def get_cumulative_time_percent_diff(self) -> float:
        """
        Percentage difference in function cumulative execution time (i.e. including children)
        between profiler runs.
        """
        if self.old_stats and self.new_stats:
            return percentage_diff(
                self.old_stats.get_cumulative_time(), self.new_stats.get_cumulative_time())
        return float('NaN')

    def get_total_time_percent_diff(self) -> float:
        """
        Percentage difference in function total execution time (i.e. excluding children) between
        profiler runs.
        """
        if self.old_stats and self.new_stats:
            return percentage_diff(self.old_stats.get_total_time(), self.new_stats.get_total_time())
        return float('NaN')

    def get_function_state(self) -> State:
        """
        Indicates whether function's stats can be compared between runs of the profiler. Stats are
        comparable only if the function was called in both profiler runs.
        """
        assert self.old_stats or self.new_stats

        if self.old_stats and self.new_stats:
            return self.State.COMMON

        return self.State.OLD if self.old_stats else self.State.NEW


@dataclass
class BaseProgramProfilerStats:
    """
    Class for keeping track of the program call profiler stats, i.e. function call profiler stats
    with metainformation about the profiler run.
    """

    # How long the whole profiler test took in seconds
    duration: float

    # Detailed profiler stats of the function calls tree
    function_stats: BaseFunctionProfilerStats


class BaseProgramProfilerStatsDiff(abc.ABC):
    """
    Class for keeping track a diff between profiler stats represented by the
    :class:`BaseProgramProfilerStats` class.

    The intention behind this class is to provide a tool which is capable of creating a diff (in the
    form of function calls tree) between two outputs of the same performance profiler (like
    pyinstrument or cProfile). The resulting diff is intended to be an indicator whether commit
    corresponding to one profiler output improved or degraded Wildland performance compared to the
    another profiler output.
    """

    # Stats corresponding to the 1st run of the profiler
    old_prog_stats: BaseProgramProfilerStats

    # Stats corresponding to the 2nd run of the profiler
    new_prog_stats: BaseProgramProfilerStats

    @classmethod
    @abc.abstractmethod
    def diff_stats_from_files(cls, old_profiler_json: Path, new_profiler_json: Path) \
            -> 'BaseProgramProfilerStatsDiff':
        """
        Compare profiler outputs corresponding to the same function call and return diff represented
        by a tree.
        """
        raise NotImplementedError()

    @classmethod
    def print_diff(cls, old_profiler_output: Path, new_profiler_output: Path) -> None:
        """
        Compare profiler outputs corresponding to the same function call and print the result of
        comparison on ``stdout``.
        """
        print(cls.diff_stats_from_files(old_profiler_output, new_profiler_output))


def percentage_diff(old_val: float, new_val: float) -> float:
    """
    Calculate percentage difference between given values. Return ``NaN`` in case of division by
    zero.
    """
    return (new_val - old_val) / (old_val or float('NaN'))
