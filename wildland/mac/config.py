"""
Mac/Darwin implementation of Config
"""
from ..config import Config


class MacConfig(Config):
    """
    A Config specialization for Darwin OS
    """

    __instance = None

    @staticmethod
    def shared():
        """
        Return (instantiate if neccessary) a singleton
        configuration object.
        """
        if MacConfig.__instance is None:
            MacConfig.__instance = MacConfig()
        return MacConfig.__instance

    def __init__(self):
        super().__init__(None, None, dict(), dict())
        basecfg = Config.load()
        self.base_dir = basecfg.base_dir
        self.path = basecfg.path
        self.default_fields = basecfg.default_fields
        self.file_fields = basecfg.file_fields
