#!/usr/bin/env python3
# https://gitlab.com/wildland/wildland-client/-/issues/472
#
import os
import pathlib
import sys
sys.path.insert(0, os.fspath(pathlib.Path(__file__).parent))

from wildland.cli.cli_main import main
main()
