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
        if EnvProvider.__instance == None:
            mysys = platform.system()
            if mysys == 'Darwin':
                EnvProvider.__instance = MacEnv()
            else:
                EnvProvider.__instance = WLEnv()
        return EnvProvider.__instance
