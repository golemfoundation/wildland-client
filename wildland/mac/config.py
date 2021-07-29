from ..config import Config


class MacConfig(Config):

    __instance = None

    @staticmethod
    def shared():
        if MacConfig.__instance == None:
            MacConfig.__instance = MacConfig()
        return MacConfig.__instance

    def __init__(self):
        super().__init__(None, None, dict(), dict())
        basecfg = Config.load()
        self.base_dir = basecfg.base_dir
        self.path = basecfg.path
        self.default_fields = basecfg.default_fields
        self.file_fields = basecfg.file_fields
