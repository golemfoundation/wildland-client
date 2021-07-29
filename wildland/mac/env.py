from ..wlenv import WLEnv
from .config import MacConfig


class MacEnv(WLEnv):
    """
    macOS/Darwin environment for Wildland.
    """

    def load_config(self, params: dict = None) -> MacConfig:
        """
        mac specific config provider
        """
        return MacConfig.shared()
