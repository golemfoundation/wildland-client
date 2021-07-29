import logging

from ..cli.cli_main import main
from ..config import Config
from ..envprovider import EnvProvider

logger = logging.getLogger("cli_main")

def cli_main(mountpoint: str):
    # initialize config with what we know
    cfg = EnvProvider.shared().load_config()
    cfg.override(override_fields = {'mount-dir': mountpoint})
    logger.debug("configuration bootstrapped with mountpoint %s", mountpoint)
    exit(main(None, None, None, None, cfg))
