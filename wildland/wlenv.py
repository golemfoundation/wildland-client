"""
Wildland environment for Linux systems.
"""
from .config import Config

class WLEnv:
    """
    Base environment for Wildland.
    """

    #pylint: disable=no-self-use
    def load_config(self, params: dict = None) -> Config:
        """
        load an instance of Config object, optionally
        using passed params to initialize it in a
        platform-specific way.
        """

        base_dir = None
        if params:
            base_dir = params.get('base_dir', None)
        return Config.load(base_dir)
