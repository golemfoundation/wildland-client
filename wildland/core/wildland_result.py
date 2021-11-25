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
#
# SPDX-License-Identifier: GPL-3.0-or-later

import ast
import inspect
import textwrap
from dataclasses import dataclass
from typing import Optional, List, Tuple, Union, Callable, Any


@dataclass
class WLError:
    error_code: int  # need to agree the explicit meaning
    error_description: str  # human-readable description suitable for console or log output
    is_recoverable: bool
    offender_type: Optional[str]  # i.e. WLContainer, WLFile
    offender_id: Optional[str]
    diagnostic_info: str  # diagnostic information we can dump to logs (i.e. Python backtrace
    # converted to str which is useful for a developer debugging the issue, but not for the user


class WildlandResult:
    def __init__(self):
        self.success: bool = True
        self.errors: List[WLError] = []


def wildland_result(default_output=()):
    """
    Decorator encapsulating the Wildland core outputs.

    It is used for:
    1. catch any python exception and put it to WildlandResult.errors
    2. make sure the first returned value is WildlandResult, i.e. if the first returned value isn't
    WildlandResult, it will be added at the beginning.

    In particular:
    If the method throw exception, then the decorated method will return:
    WildlandResult if default_output == ();
    (WildlandResult, default_output) if  default_output == value
    (WildlandResult, *default_output) if  default_output is tuple.

    If the method have no explicit `return` statement,
    then the decorated method will return just WildlandResult;
    if the method returns a value,
    then the decorated method will return tuple: (WildlandResult, value);
    if the method returns a WildlandResult,
    then the decorated method will return the same WildlandResult (decorator does nothing);
    if the method returns tuple: (v1, v2, ...),
    then the decorated method will return tuple: (WildlandResult, v1, v2, ...);
    if the method returns tuple (WildlandResult, v1, v2, ...),
    then the decorated method will return the same tuple (decorator does nothing).

    @return: Decorated method which returns WildlandResult follows by method result.
    """
    def decorator(func: Callable[..., Any]):
        def inner(*arg: Any, **kwargs: Any) \
                -> Union[WildlandResult, Tuple[WildlandResult, ...]]:
            try:
                func_result = func(*arg, **kwargs)
            except Exception as e:
                wl_error = WLError(-1, str(e), False, None, None, "WL core error.")
                wl_result = WildlandResult()
                wl_result.success = False
                wl_result.errors.append(wl_error)
                if default_output == ():
                    return wl_result
                if isinstance(default_output, tuple):
                    return wl_result, *default_output
                return wl_result, default_output

            wl_result = WildlandResult()

            if _not_contains_explicit_return(func):
                return wl_result

            if isinstance(func_result, tuple):
                if isinstance(func_result[0], WildlandResult):
                    return func_result
                return wl_result, *func_result

            if isinstance(func_result, WildlandResult):
                return func_result

            return wl_result, func_result

        return inner

    return decorator


def _not_contains_explicit_return(f: Callable):
    if callable(f) and f.__name__ == "<lambda>":
        return False
    return not any(isinstance(node, ast.Return)
                   for node in ast.walk(ast.parse(textwrap.dedent(inspect.getsource(f)))))
