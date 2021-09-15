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
Performance analyzer and printer to be used directly by CI scripts
"""

import argparse
import math
import sys

from pathlib import Path
from typing import List, Optional
from colorama import Fore, Style

from .pyinstrument_profiler_diff import (
    PyinstrumentFunctionProfilerStatsDiff,
    PyinstrumentProgramProfilerStatsDiff,
)


class PyinstrumentStatsDiffPrinterError(Exception):
    """
    Exception thrown whenever unexpected error is detected.
    """


class PyinstrumentStatsDiffPrinter:
    """
    Traverses diff :class:`PyinstrumentProgramProfilerStatsDiff` tree and decides performance of
    which function calls degraded sufficiently enough to print an alert about it.
    """

    # Acceptable percentage level of function execution time performance drop
    default_performance_drop_tolerance = 0.05
    fun_call_formatter = "{: <70}"
    cumulative_time_diff_formatter = "{: >18}"
    cumulative_time_percent_diff_formatter = "{: >18}"
    total_time_diff_formatter = "{: >18}"
    total_time_percent_diff_formatter = "{: >18}"
    fun_state_formatter = "{: >18}"

    def __init__(
        self,
        old_profiler_json: Path,
        new_profiler_json: Path,
        performance_drop_tolerance: float = default_performance_drop_tolerance,
        print_cum_time_diff: bool = True,
        print_tot_time_diff: bool = True,
        print_fun_state: bool = True,
        print_only_common_functions=False,
    ):
        self.performance_drop_tolerance = performance_drop_tolerance
        self.print_cum_time_diff = print_cum_time_diff
        self.print_tot_time_diff = print_tot_time_diff
        self.print_fun_state = print_fun_state
        self.print_only_common_functions = print_only_common_functions
        self.diff_tree = PyinstrumentProgramProfilerStatsDiff.diff_stats_from_files(
            old_profiler_json, new_profiler_json
        )

    def is_performacne_drop_acceptable(self, print_msg: bool = True) -> bool:
        """
        Determines whether performance test passed. This method is needed for CI scripts to exit
        with error status code if the test failed.
        """
        root = self._get_diff_root()
        performance_drop = root.get_cumulative_time_percent_diff()
        performance_acceptable = performance_drop <= self.performance_drop_tolerance

        if print_msg:
            if performance_acceptable:
                msg = Fore.GREEN + "passed"
            else:
                msg = Fore.RED + "failed"

            print(f"Performance test {Style.BRIGHT}{msg}{Style.RESET_ALL} " \
                  f"(max acceptable drop: {self.performance_drop_tolerance * 100.0} %, " \
                  f"is: {performance_drop * 100.0} %).", file=sys.stderr)

        return performance_acceptable

    def print_performance_issues(self, max_depth: Optional[int] = None) -> None:
        """
        Print full function calls diff-tree with highlighted performance issues.
        """
        self.is_performacne_drop_acceptable(print_msg=True)
        print(file=sys.stderr)
        print("Function calls stats diff:", file=sys.stderr)
        print(file=sys.stderr)
        root = self._get_diff_root()
        prefix: List[str] = []
        self._print_column_titles()
        self._print_function_diff_stats(root, prefix, max_depth=max_depth)

    def _get_diff_root(self) -> PyinstrumentFunctionProfilerStatsDiff:
        root = self.diff_tree.root_diff

        if not root:
            err_msg = "Trees correspond to different function calls ({} vs {}).".format(
                self.diff_tree.old_prog_stats.function_stats.function_name,
                self.diff_tree.new_prog_stats.function_stats.function_name,
            )
            raise PyinstrumentStatsDiffPrinterError(err_msg)

        return root

    def _print_column_titles(self) -> None:
        formatter = self.fun_call_formatter

        columns = ["function name"]

        if self.print_cum_time_diff:
            columns.extend(["cum_time diff", "cum_time diff %"])
            formatter += (
                self.cumulative_time_diff_formatter + self.cumulative_time_percent_diff_formatter
            )

        if self.print_tot_time_diff:
            columns.extend(["tot_time diff", "tot_time diff %"])
            formatter += self.total_time_diff_formatter + self.total_time_percent_diff_formatter

        if self.print_fun_state:
            columns.append("fun_state")
            formatter += self.fun_state_formatter

        print(formatter.format(*columns), file=sys.stderr)

    def _print_function_diff_stats(
        self,
        node: PyinstrumentFunctionProfilerStatsDiff,
        prefix: List[str],
        max_depth: Optional[int] = None,
        is_last_children: bool = True,
    ) -> None:
        """
        Recursively print whole diff-tree.
        """
        if max_depth is not None and max_depth < 1:
            return

        if (
            self.print_only_common_functions
            and node.get_function_state() != PyinstrumentFunctionProfilerStatsDiff.State.COMMON
        ):
            return

        prefix_string = "".join(prefix)

        if is_last_children:
            decorator = "└── "
            prefix.append("    ")
        else:
            decorator = "├── "
            prefix.append("│   ")

        self._print_node(node, prefix_string, decorator)

        new_depth = max_depth - 1 if max_depth else None
        children = list(node.children.values())

        for c in children[:-1]:
            self._print_function_diff_stats(c, prefix, new_depth, False)

        if len(children) > 0:
            self._print_function_diff_stats(children[-1], prefix, new_depth, True)

        prefix.pop()

    def _print_node(
        self,
        node: PyinstrumentFunctionProfilerStatsDiff,
        prefix_string: str,
        decorator: str,
    ) -> None:
        function_name = node.get_function_name()

        formatter = self.fun_call_formatter
        columns = [f"{prefix_string}{decorator}{function_name}"]

        if self.print_cum_time_diff:
            cumulative_time_diff = node.get_cumulative_time_diff()
            cumulative_time_percent_diff = node.get_cumulative_time_percent_diff()
            columns.extend(
                [
                    f"{cumulative_time_diff:+.5} sec",
                    f"{100.0 * cumulative_time_percent_diff:+.5} %",
                ]
            )
            formatter += self.cumulative_time_diff_formatter + self.get_colored(
                cumulative_time_percent_diff, self.cumulative_time_percent_diff_formatter
            )

        if self.print_tot_time_diff:
            total_time_diff = node.get_total_time_diff()
            total_time_percent_diff = node.get_total_time_percent_diff()
            columns.extend(
                [
                    f"{total_time_diff:+.5} sec",
                    f"{100.0 * total_time_percent_diff:+.5} %",
                ]
            )
            formatter += self.total_time_diff_formatter + self.get_colored(
                total_time_percent_diff, self.total_time_percent_diff_formatter
            )

        if self.print_fun_state:
            state = node.get_function_state()
            columns.append(str(state))
            formatter += self.fun_state_formatter

        print(formatter.format(*columns))

    def get_colored(self, percent: float, string: str) -> str:
        """
        Get a colored string if the threshold is exceeded.
        """
        if 0 <= percent <= self.performance_drop_tolerance or math.isnan(percent):
            return string

        if percent > self.performance_drop_tolerance:
            color = Fore.RED
        else:
            color = Fore.GREEN

        return color + Style.BRIGHT + string + Style.RESET_ALL


def main() -> None:
    """
    Entry point.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "old_json_path",
        help="Path to the JSON output file corresponding to the first performance profiler run "
        "(a.k.a. old one).",
    )
    parser.add_argument(
        "new_json_path",
        help="Path to the JSON output file corresponding to the second performance profiler run "
        "(a.k.a. new one).",
    )

    args = parser.parse_args()
    analyzer = PyinstrumentStatsDiffPrinter(args.old_json_path, args.new_json_path)
    analyzer.print_performance_issues()


if __name__ == "__main__":
    main()
