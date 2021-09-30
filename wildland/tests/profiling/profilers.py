# Wildland Project
#
# Copyright (C) 2021 Golem Foundation
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
Performance profilers
"""

import abc
import os
import sys

from pathlib import Path
from typing import Any, Callable, Tuple, Union

import cProfile
import pstats


class WildlandProfiler(metaclass=abc.ABCMeta):
    """
    Base class for Wildland performance profilers.
    """

    # This static variable helps with determining whether the callable passed to ``run`` method is
    # already indirectly under the profiler. For example, if function ``f`` calls function ``g`` and
    # both of them are decorated with ``@profile``, then function ``g`` should not be wrapped with
    # yet another profiler calls because it is already taken into an account by ``f``'s decorator.
    already_under_profiler: bool = False

    def __init__(self, output_file_ext: str):
        self.output_file_ext = output_file_ext

    @abc.abstractmethod
    def _run_profiler(
        self, artifacts_dir: Path, print_stats: bool, func: Callable, *args, **kwargs
    ) -> Any:
        raise NotImplementedError()

    def run(self, artifacts_dir: Path, print_stats: bool, func: Callable, *args, **kwargs) -> Any:
        """
        Run profiler against given callable and save results to the given path. Optionally print
        stats on the stdout or stderr as well.
        """
        if WildlandProfiler.already_under_profiler:
            return func(*args, **kwargs)

        WildlandProfiler.already_under_profiler = True
        result = self._run_profiler(artifacts_dir, print_stats, func, *args, **kwargs)
        WildlandProfiler.already_under_profiler = False

        return result

    @staticmethod
    def _get_test_name() -> str:
        """
        Try to get pytest test name. Empty string is returned if the test name cannot be determined.

        TODO We assume ``PYTEST_CURRENT_TEST`` format, which is unreliable. See
        https://stackoverflow.com/a/51955499/1321680) to learn more.
        """
        return os.environ.get("PYTEST_CURRENT_TEST", "").split(":")[-1].split(" ")[0]

    def _generate_report_path(
        self, output_dir: Path, test_func: Callable, suffix: str = ""
    ) -> Path:
        """
        Generate next path for the file holding profiling details of the currently running test.

        For example, if you run::

            pytest -x -k test_multiple_storage_mount

        and decorate :func:`wildland.cli.cli_container._mount` function with ``@cprofile()``
        decorator and the following file already exists::

            ./artifacts/test_multiple_storage_mount/wildland.cli.cli_container._mount.001.cprofile

        then the generated path is::

            ./artifacts/test_multiple_storage_mount/wildland.cli.cli_container._mount.002.cprofile
        """
        test_name = self._get_test_name()
        output_dir /= test_name
        output_dir.mkdir(parents=True, exist_ok=True)

        module_name = test_func.__module__
        func_name = test_func.__name__
        counter = 0

        while True:
            counter += 1
            file_name = f"{module_name}.{func_name}.{counter:03d}.{self.output_file_ext}{suffix}"
            path = output_dir / file_name
            if not Path(path).exists():
                break

        return path


class WildlandCProfiler(WildlandProfiler):
    """
    Performance profiler based on cProfile.
    """

    def __init__(
        self,
        output_file_ext: str = "cprofile",
        strip_dirs: bool = False,
        sort: str = "cumulative",
        lines: int = 50,
    ):
        super().__init__(output_file_ext)
        self.strip_dirs = strip_dirs
        self.sort = sort
        self.lines = lines

    def _run_profiler(
        self, artifacts_dir: Path, print_stats: bool, func: Callable, *args, **kwargs
    ) -> Any:
        prof = cProfile.Profile()
        retval = prof.runcall(func, *args, **kwargs)
        report_path = self._generate_report_path(artifacts_dir, func)
        prof.dump_stats(report_path)

        if print_stats:
            stats = pstats.Stats(str(report_path))

            if self.strip_dirs:
                stats.strip_dirs()

            if isinstance(self.sort, (tuple, list)):
                stats.sort_stats(*self.sort)
            else:
                stats.sort_stats(self.sort)

            stats.print_stats(self.lines)

        return retval


class WildlandPyinstrumentProfiler(WildlandProfiler):
    """
    Performance profiler based on pyinstrument.
    """

    def __init__(
        self,
        output_file_ext: str = "iprofile",
        sampling_interval=0.0001,
        unicode: bool = True,
        color: bool = True,
        show_all: bool = True,
        timeline: bool = False,
    ):
        super().__init__(output_file_ext)
        self.sampling_interval = sampling_interval
        self.unicode = unicode
        self.color = color
        self.show_all = show_all
        self.timeline = timeline

    def _run_profiler(
        self, artifacts_dir: Path, print_stats: bool, func: Callable, *args, **kwargs
    ) -> Any:
        # pylint: disable=import-outside-toplevel
        import pyinstrument
        from pyinstrument.renderers import JSONRenderer

        with pyinstrument.Profiler(interval=self.sampling_interval) as profiler:
            returned_val = func(*args, **kwargs)

        file_formats: Tuple[Any, ...] = (
            (".html", profiler.output_html, ()),
            (".txt", profiler.output_text, ()),
            (".json", profiler.output, (JSONRenderer(show_all=False, timeline=False))),
        )

        for file_ext, report_func, *args in file_formats:
            report_path = self._generate_report_path(artifacts_dir, func, file_ext)
            with open(report_path, "w") as f:
                report = report_func(*args)
                f.write(report)

        if print_stats:
            print(
                profiler.output_text(
                    unicode=self.unicode,
                    color=self.color,
                    show_all=self.show_all,
                    timeline=self.timeline,
                )
            )

        return returned_val


def _is_test_env() -> bool:
    """
    Determine whether running under pytest or Wildland CI test.

    See https://stackoverflow.com/a/44595269/1321680 to learn more.
    """
    return "pytest" in sys.modules or "WILDLAND_TEST" in os.environ


def _profile(
    artifacts_path: Path = Path("artifacts/profiler_results"),
    is_test_env: Union[bool, Callable[[], bool]] = _is_test_env,
    profiler: WildlandProfiler = WildlandPyinstrumentProfiler(),
    print_stats: bool = False,
) -> Callable:
    """
    A decorator which profiles a callable only if test environment is detected.
    """

    def decorator(func):
        def wrapper(*args, **kwargs):
            tested_fun_name = getattr(func, "__name__", repr(func))
            artifacts_subpath = artifacts_path / tested_fun_name
            return profiler.run(artifacts_subpath, print_stats, func, *args, **kwargs)

        use_profiler_decorator = _is_test_env() if callable(is_test_env) else is_test_env
        return wrapper if use_profiler_decorator else func

    return decorator


def cprofile(**kwargs) -> Callable:
    """
    cProfile profiling decorator.
    """
    return _profile(profiler=WildlandCProfiler(), **kwargs)


def iprofile(**kwargs) -> Callable:
    """
    pyinstrument profiling decorator.
    """
    return _profile(profiler=WildlandPyinstrumentProfiler(), **kwargs)


def profile(**kwargs) -> Callable:
    """
    Default profiling decorator.
    """
    profiler: WildlandProfiler

    if "USE_CPROFILER_FOR_WILDLAND_PROFILING" in os.environ:
        profiler = WildlandCProfiler()
    else:
        profiler = WildlandPyinstrumentProfiler()

    return _profile(profiler=profiler, **kwargs)
