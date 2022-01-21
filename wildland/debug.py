# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
#                    Michał Haponiuk <mhaponiuk@wildland.io>,
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
Helpful functions to start vscode debugger listener in the background.
"""

import os
import time
from distutils.util import strtobool
from typing import List, Optional

from psutil import Process, process_iter

from wildland.log import get_logger

logger = get_logger(__name__)

PORT = 5678

def _find_proc_by_name(name: str) -> List[Process]:
    ls = []
    p: Process
    for p in process_iter(["name", "cmdline"]):
        cmdline: str = " ".join(p.info['cmdline'])
        if name in p.info['name'] or name in cmdline:
            ls.append(p)
    return ls

def _find_pydevd_server() -> Optional[Process]:
    ps: List[Process] = _find_proc_by_name('pydevd')
    how_many: int = len(ps)
    assert how_many in (0, 1)
    return ps[0] if how_many else None

def _kill_debugpy_if_exists() -> bool:
    p_debugpy = _find_pydevd_server()
    if p_debugpy:
        logger.warning("killing debugpy sever")
        p_debugpy.kill()
        return True
    return False

def _start_debugpy_server() -> None:
    # pylint: disable=import-outside-toplevel
    import debugpy
    if debugpy.is_client_connected():
        return
    try:
        debugpy.listen(("0.0.0.0", PORT))
        logger.debug('debugpy listen on port %i', PORT)
    except RuntimeError:
        logger.error("INSIDE exception")
        # probably process is sleeping but it wasn't been checked well
        # assert _find_pydevd_server().status() == 'sleeping'
        if _kill_debugpy_if_exists():
            time.sleep(1)
            debugpy.listen(("0.0.0.0", PORT))
            logger.error('debugpy listen on port %i', PORT)
    if _find_pydevd_server():
        debugpy.connect(("0.0.0.0", PORT))
    env_debugpy_wait: bool = strtobool(os.environ.get("DEBUGPY__WAIT", "False"))
    if env_debugpy_wait:
        logger.warning("waiting for vscode remote attach")
        debugpy.wait_for_client()

def start_debugpy_server_if_enabled() -> None:
    """
    Starts debugpy listener in the background.
    Can be blocking until debugger attached -- see DEBUGPY environment vars.
    """
    env_debugpy: bool = strtobool(os.environ.get("DEBUGPY", "False"))
    if env_debugpy:
        _start_debugpy_server()
