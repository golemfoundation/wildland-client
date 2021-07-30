"""
Environment provider for Wildland. This class provides several
objects representing to Wildland its runtime environment in
platform independent way, so that the rest of core code can
rely on this rather than assuming a specific OS on its own.
"""
import platform

from .wlenv import WLEnv
from .mac.env import MacEnv

class EnvProvider:
    """
    Provider class for platform specific environment data.
    """

    __instance: WLEnv = None

    @staticmethod
    def shared():
        """
        return shared instance of platform-specific
        environment object.
        """
        if EnvProvider.__instance is None:
            mysys = platform.system()
            if mysys == 'Darwin':
                EnvProvider.__instance = MacEnv()
            else:
                EnvProvider.__instance = WLEnv()
        return EnvProvider.__instance
