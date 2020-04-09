'''
Wildland command-line interface.
'''

import argparse
from pathlib import Path
import sys

from .user import create_user, default_user_dir, UserRepository
from .sig import DummySigContext, GpgSigContext
from .manifest import Manifest, ManifestError

parser = argparse.ArgumentParser()
parser.add_argument(
    '--user-dir', default=default_user_dir(),
    help='Directory for user manifests')
parser.add_argument(
    '--dummy', action='store_true',
    help='Use dummy signatures')
parser.add_argument(
    '--gpg-home',
    help='Use a different GPG home directory')
subparsers = parser.add_subparsers(dest='command', title='Commands')

parser_create_user = subparsers.add_parser(
    'create-user',
    help='Create a new user (needs a GPG key)')
parser_create_user.add_argument(
    'key',
    help='GPG key identifier')
parser_create_user.add_argument(
    '--name',
    help='Name for file')

parser_list_users = subparsers.add_parser(
    'list-users',
    help='List users')

parser_sign = subparsers.add_parser(
    'sign',
    help='Add a signature to a manifest')
parser_sign.add_argument(
    'input_file', metavar='FILE', nargs='?',
    help='File to sign (default is stdin)')
parser_sign.add_argument(
    '-o', dest='output_file', metavar='FILE',
    help='Output file (default is stdout)')
parser_sign.add_argument(
    '-i', dest='in_place', action='store_true',
    help='Modify the file in place')

parser_sign = subparsers.add_parser(
    'verify',
    help='Verify manifest signature')
parser_sign.add_argument(
    'input_file', metavar='FILE', nargs='?',
    help='File to verify (default is stdin)')


def main():
    '''
    Wildland CLI entry point
    '''

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    user_dir = Path(args.user_dir)

    if args.dummy:
        sig = DummySigContext()
    else:
        sig = GpgSigContext(args.gpg_home)
    user_repository = UserRepository(sig)
    user_repository.load_users(user_dir)

    if args.command == 'create-user':
        pubkey = sig.find(args.key)
        print('Using key: {}'.format(pubkey))
        sig.add_signer(pubkey)
        path = create_user(user_dir, pubkey, sig, args.name)
        print('Created: {}'.format(path))

    if args.command == 'list-users':
        for user in user_repository.users.values():
            print('{} {}'.format(user.pubkey, user.manifest_path))

    if args.command == 'sign':
        if args.in_place:
            if not args.input_file:
                print('Cannot -i without a file')
                sys.exit(1)
            if args.output_file:
                print('Cannot use both -i and -o')
                sys.exit(1)
            args.output_file = args.input_file

        if args.input_file:
            with open(args.input_file, 'rb') as f:
                data = f.read()
        else:
            data = sys.stdin.buffer.read()

        manifest = Manifest.from_unsigned_bytes(data, sig)
        signed_data = manifest.to_bytes()

        if args.output_file:
            with open(args.output_file, 'wb') as f:
                f.write(signed_data)
        else:
            sys.stdout.buffer.write(signed_data)

    if args.command == 'verify':
        if args.input_file:
            with open(args.input_file, 'rb') as f:
                data = f.read()
        else:
            data = sys.stdin.buffer.read()

        try:
            manifest = Manifest.from_bytes(data, sig)
        except ManifestError as e:
            print(e)
            sys.exit(1)
        print('Manifest is OK')

if __name__ == '__main__':
    main()
