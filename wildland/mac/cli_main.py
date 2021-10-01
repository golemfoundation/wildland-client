# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
#    Piotr K. Isajew  <piotr@wildland.io>
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
main program for the CLI on mac.
"""
import logging
import sys

from ..cli.cli_main import main
from ..envprovider import EnvProvider

logger = logging.getLogger("cli_main")

def cli_main(mountpoint: str):
    """
    Main method (supposed to be executed after bootstraping
    Python in the CLI program. This essentially sets up
    the configuration object and delegates further execution
    to the Linux CLI.
    """
    # initialize config with what we know
    cfg = EnvProvider.shared().load_config()
    cfg.override(override_fields = {'mount-dir': mountpoint})
    logger.debug("configuration bootstrapped with mountpoint %s", mountpoint)
    sys.exit(main(ctx=None, base_dir=None, dummy=None, debug=None,
                      verbose=None, version=None))
