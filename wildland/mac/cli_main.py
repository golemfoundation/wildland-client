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
    sys.exit(main(None, None, None, None, cfg))
