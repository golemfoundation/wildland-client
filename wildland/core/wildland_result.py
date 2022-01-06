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
"""
Result of Wildland Core operations
"""
import ast
import inspect
import textwrap
from dataclasses import dataclass
from typing import Optional, List, Tuple, Union, Callable, Any
import binascii

from ..manifest.manifest import ManifestError
from ..manifest.sig import SigError
from ..manifest.schema import SchemaError
from .wildland_objects_api import WLObjectType


@dataclass
class WLError:
    """
    Representation of errors raised by Wildland Core
    """

    error_code: int  # need to agree the explicit meaning
    error_description: str  # human-readable description suitable for console or log output
    is_recoverable: bool
    offender_type: Optional[WLObjectType] = None
    offender_id: Optional[str] = None
    diagnostic_info: Optional[str] = None  # diagnostic information we can dump to logs (i.e. Python
    # backtrace converted to str which is useful for a developer debugging the issue, but not
    # for the user

    @classmethod
    def from_exception(cls, exc: Exception, is_recoverable: bool = False):
        """
        Generate a WLError from an Exception.
        :param exc: source Exception
        :param is_recoverable: whether the error can be recovered from
        """
        # TODO: improve error reporting, add more information
        error_desc = str(exc)
        if isinstance(exc, ManifestError):
            err_code = 1
        elif isinstance(exc, SigError):
            err_code = 2
        elif isinstance(exc, SchemaError):
            err_code = 3
        elif isinstance(exc, binascii.Error):
            err_code = 101
            error_desc = "Incorrect public key provided; provide key, not filename or path."
        elif isinstance(exc, FileExistsError):
            err_code = 4
        else:
            err_code = 999
        error = cls(error_code=err_code, error_description=error_desc,
                    is_recoverable=is_recoverable)
        return error
# Temporary documentation of additional error codes; to be organized and reqritten once needed
# errors are collected:
# 100 - at least one public key needed for user
# 101 - public key in use by other users
# 700 - unknown object type


class WildlandResult:
    """
    Result of Wildland Core operation; contains list of errors and a simple helper function
    to show whether there are any unrecoverable errors.
    """
    def __init__(self):
        self.errors: List[WLError] = []

    @property
    def success(self):
        """
        property that shows whether any unrecoverable errors occurred
        """
        for e in self.errors:
            if not e.is_recoverable:
                return False
        return True

    def __str__(self):
        result = ""
        for e in self.errors:
            result += f"{e.error_code} - {e.error_description}\n"
        return result


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
                wl_error = WLError.from_exception(e)
                wl_result = WildlandResult()
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
