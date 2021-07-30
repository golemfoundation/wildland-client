"""
Darwin OS environment for Wildland.
"""

from ..wlenv import WLEnv
from .config import MacConfig


class MacEnv(WLEnv):
    """
    A WLEnv specialization for macOS/Darwin environment.
    """

    def load_config(self, params: dict = None) -> MacConfig:
        """
        mac specific config provider
        """
        return MacConfig.shared()
