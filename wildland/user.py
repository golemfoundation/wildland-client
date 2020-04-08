
from pathlib import Path
import os
from typing import Dict

from .manifest import Manifest
from .schema import Schema
from .sig import SigContext


class User:
    '''Wildland user'''

    SCHEMA = Schema('user')

    def __init__(self, manifest: Manifest, manifest_path=None):
        self.manifest = manifest
        self.manifest_path = manifest_path
        self.pubkey = manifest.fields['pubkey']

    @classmethod
    def from_file(cls, path, sig_context: SigContext) -> 'User':
        manifest = Manifest.from_file(path, sig_context, cls.SCHEMA,
                                      self_signed=True)
        return cls(manifest, path)


def default_user_dir() -> Path:
    home_dir = os.getenv('HOME')
    assert home_dir
    return Path(home_dir) / '.wildland/users'


class UserRepository:
    def __init__(self, sig_context: SigContext):
        self.users: Dict[str, User] = {}
        self.sig_context = sig_context

    def add_user(self, user):
        self.users[user.pubkey] = user
        self.sig_context.add_signer(user.pubkey)

    def load_users(self, user_dir: Path):
        for name in os.listdir(user_dir):
            path = user_dir / name
            user = User.from_file(path, self.sig_context)
            self.add_user(user)


def create_user(user_dir: Path, pubkey, sig_context: SigContext, name=None) -> Path:
    manifest = Manifest.from_fields({
        'signer': pubkey,
        'pubkey': pubkey,
    }, sig_context)
    manifest_data = manifest.to_bytes()

    if name is None:
        name = pubkey
    if not os.path.exists(user_dir):
        os.makedirs(user_dir)
    path = user_dir / f'{name}.yaml'
    with open(path, 'wb') as f:
        f.write(manifest_data)
    return path
