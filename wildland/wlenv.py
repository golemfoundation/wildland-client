"""
At some point this should provide OS-independent
environment information (i.e. config location,
temporary storage directory, etc.) for internal
wildland usage.
"""

import os
from pathlib import PurePosixPath, Path

class WLEnv:
    """
    WLEnv class provides information to parts of Wildland
    that need to interact with the OS environment in system
    independent way.
    """

    def __init__(self):
        super().__init__()
        default = Path('~/.local/share/').expanduser()
        self._storage_dir = PurePosixPath(os.getenv('XDG_HOME_DATA',
                                                    default)) / 'wl'

    def storage_dir(self) -> PurePosixPath:
        """
        returns path to root directory of wildland dedicated storage
        area.
        """
        return self._storage_dir

    def temp_root(self) -> PurePosixPath:
        """
        return a root of temporary directory
        """
        return self.storage_dir() / 'tmp'
