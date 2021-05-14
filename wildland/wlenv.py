"""
At some point this should provide OS-independent
environment information (i.e. config location, 
temporary storage directory, etc.) for internal
wildland usage.
"""

import os
from pathlib import PurePosixPath, Path

class WLEnv:

    def storage_dir(self) -> PurePosixPath:
        """
        returns path to root directory of wildland dedicated storage
        area.
        """
        default = Path('~/.local/share/').expanduser()
        return PurePosixPath(os.getenv('XDG_HOME_DATA', default)) / 'wl'

    def temp_root(self) -> PurePosixPath:
        """
        return a root of temporary directory
        """
        return self.storage_dir() / 'tmp'
