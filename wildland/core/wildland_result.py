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
import sys
import textwrap
import traceback
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Tuple, Union, Callable, Any
import binascii

from ..manifest.manifest import ManifestError
from ..manifest.sig import SigError
from ..manifest.schema import SchemaError
from .wildland_objects_api import WLObjectType


class WLErrorType(Enum):
    """
    Listing of possible WL error types.
    """
    MANIFEST_ERROR = 1, "Incorrect manifest"
    SIGNATURE_ERROR = 2, "Incorrect signature"
    SCHEMA_ERROR = 3, "Schema error"
    FILE_EXISTS_ERROR = 4, "File exists"  # offender_id is the name/id of whatever already exists
    NOT_IMPLEMENTED = 99, "Not implemented"
    PUBKEY_NEEDED = 100, "At least one public key must be provided"
    PUBKEY_FORMAT_ERROR = 101, "Incorrect public key provided; provide key, not filename or path"
    PUBKEY_IN_USE = 102, "Public key used by other users as secondary key"
    UNKNOWN_OBJECT_TYPE = 700, "Unknown object type"
    SYNC_FOR_CONTAINER_NOT_RUNNING = 800, "Sync not running for this container"
    SYNC_FOR_CONTAINER_ALREADY_RUNNING = 801, "Sync already running for this container"
    SYNC_MANAGER_NOT_ACTIVE = 802, "Sync manager not active"
    SYNC_MANAGER_ALREADY_ACTIVE = 803, "Sync manager already active"
    SYNC_FAILED_TO_COMMUNICATE_WITH_MANAGER = 804, "Failed to communicate with sync manager"
    SYNC_CALLBACK_NOT_FOUND = 805, "Sync event handler not found"
    OTHER = 999, None

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        return str(self.name)


@dataclass
class WLError:
    """
    Representation of errors raised by Wildland Core
    """

    code: WLErrorType  # need to agree the explicit meaning
    description: Optional[str] = None  # human-readable description suitable for console or log
    is_recoverable: bool = False
    offender_type: Optional[WLObjectType] = None
    offender_id: Optional[str] = None
    diagnostic_info: Optional[str] = None  # diagnostic information we can dump to logs (i.e. Python
    # backtrace converted to str which is useful for a developer debugging the issue, but not
    # for the user)

    def __post_init__(self):
        if self.description is None:
            self.description = self.code.value[1]

    @classmethod
    def from_exception(cls, exc: Exception, is_recoverable: bool = False):
        """
        Generate a WLError from an Exception.
        :param exc: source Exception
        :param is_recoverable: whether the error can be recovered from
        """
        # TODO: improve error reporting, add more information
        err_desc = None
        offender_id = None
        if isinstance(exc, ManifestError):
            err_code = WLErrorType.MANIFEST_ERROR
        elif isinstance(exc, SigError):
            err_code = WLErrorType.SIGNATURE_ERROR
        elif isinstance(exc, SchemaError):
            err_code = WLErrorType.SCHEMA_ERROR
        elif isinstance(exc, binascii.Error):
            err_code = WLErrorType.PUBKEY_FORMAT_ERROR
        elif isinstance(exc, FileExistsError):
            err_code = WLErrorType.FILE_EXISTS_ERROR
            err_desc = f'{err_code.value[1]}: {exc}'
            offender_id = str(exc)  # name of whatever was already existing
        elif isinstance(exc, NotImplementedError):
            err_code = WLErrorType.NOT_IMPLEMENTED
        else:
            err_code = WLErrorType.OTHER
            err_desc = str(exc)

        error = cls(code=err_code, description=err_desc,
                    is_recoverable=is_recoverable,
                    offender_id=offender_id,
                    diagnostic_info=''.join(traceback.format_exception(*sys.exc_info())))
        return error


class WildlandResult:
    """
    Result of Wildland Core operation; contains list of errors and a simple helper function
    to show whether there are any unrecoverable errors.
    """
    _OK = None  # static instance representing successful result

    def __init__(self):
        self.errors: List[WLError] = []

    @classmethod
    def OK(cls) -> 'WildlandResult':
        """
        Static instance representing successful result.
        """
        if not cls._OK:
            cls._OK = WildlandResult()

        return cls._OK

    @classmethod
    def error(cls, code: WLErrorType, description: Optional[str] = None,
              is_recoverable: bool = False, offender_type: Optional[WLObjectType] = None,
              offender_id: Optional[str] = None, diagnostic_info: Optional[str] = None) \
            -> 'WildlandResult':
        """
        Return WildlandResult containing a WLError.
        """
        result = WildlandResult()
        result.errors.append(WLError(code=code, description=description,
                                     is_recoverable=is_recoverable, offender_type=offender_type,
                                     offender_id=offender_id, diagnostic_info=diagnostic_info))
        return result

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
        if self.success:
            return "OK"

        result = ""
        for e in self.errors:
            if len(result) > 0:
                result += "\n"
            result += f"{e.code} - {e.description}"
        return result

    def __repr__(self):
        return self.__str__()


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
