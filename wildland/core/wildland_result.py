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


def wildland_result(func: Callable[..., Any]):

    def inner(*arg: Any, **kwargs: Any) \
            -> Union[WildlandResult, Tuple[WildlandResult, ...]]:
        try:
            func_result = func(*arg, **kwargs)
        except Exception as e:
            wl_error = WLError(-1, str(e), False, None, None, "WL core error.")
            wl_result = WildlandResult()
            wl_result.success = False
            wl_result.errors.append(wl_error)
            return wl_result

        wl_result = WildlandResult()

        if func_result is None:
            return wl_result

        if isinstance(func_result, tuple):
            if isinstance(func_result[0], WildlandResult):
                return func_result

            return wl_result, *func_result

        if isinstance(func_result, WildlandResult):
            return func_result

        return wl_result, func_result

    return inner
