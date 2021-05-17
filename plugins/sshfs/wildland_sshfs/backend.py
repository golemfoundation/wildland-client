"""
Wildland storage backend using sshfs
"""

import logging
from pathlib import PurePosixPath
from subprocess import Popen, PIPE, STDOUT, run

import click

from wildland.fs_client import WildlandFSError
from .local_proxy import LocalProxy

logger = logging.getLogger('storage-sshfs')


class SshFsBackend(LocalProxy):
    """
    sshfs backend
    """

    TYPE='sshfs'

    def __init__(self, **kwds):
        super().__init__(**kwds)

        self.sshfs_cmd = kwds['params']['cmd']
        self.inner_mount_point = None
        self.sshfs_host = kwds['params']['host']
        self.sshfs_path = kwds['params']['path']
        self.mount_opts = kwds['params'].get('mount_opts')
        self.login = kwds['params']['login']
        self.passwd = kwds['params'].get('passwd')
        self.identity = kwds['params'].get('identity')

    ### Abstract method implementations
    def unmount_inner_fs(self, path: PurePosixPath) -> None:
        cmd = ["umount", str(path)]
        res = run(cmd, stderr=PIPE, check=True)
        if res.returncode != 0:
            logger.error("unable to unmount sshfs (%d)",
                         res.returncode)
        if len(res.stderr) > 0:
            logger.error(res.stderr.decode())


    def mount_inner_fs(self, path: PurePosixPath) -> None:
        cmd = [self.sshfs_cmd]
        if self.passwd:
            cmd.extend(['-o', 'password_stdin'])
        if self.identity:
            ipath = self.backend_dir() / '.identity'
            with open(ipath, 'w') as of:
                of.write(self.identity)
                cmd.extend(['-o', f'IdentityFile={ipath}'])

        if self.mount_opts:
            cmd.append(self.mount_opts)

        addr = self.sshfs_host
        if self.sshfs_path:
            addr += ':' + self.sshfs_path
        if self.login:
            addr = self.login + '@' + addr

        cmd.append(addr)
        cmd.append(str(path))

        with Popen(cmd, stdout=PIPE, stdin=PIPE, stderr=STDOUT) as executor:
            out, _ = executor.communicate(bytes(self.passwd, 'utf-8'))

            if executor.returncode != 0:
                logger.error("Failed to mount sshfs filesystem (%d)",
                             executor.returncode)
                if len(out.decode()) > 0:
                    logger.error(out.decode())
                raise WildlandFSError("unable to mount sshfs")

    @classmethod
    def cli_create(cls, data):

        if data['ssh_identity'] and data['pwprompt']:
            raise click.UsageError('pwprompt and ssh-identity are mutually exclusive')
        conf = {
            'cmd': data['sshfs_command'],
            'login': data['ssh_user'],
            'mount_opts': data['mount_options'],
            'host': data['host'],
            'path': data['path']
        }


        if data['pwprompt']:
            conf['passwd'] = click.prompt('SSH password',
                                          hide_input=True)

        if data['ssh_identity']:
            with open(data['ssh_identity']) as f:
                conf['identity'] = f.readlines()
        return conf

    @classmethod
    def cli_options(cls):
        return [
            click.Option(['--sshfs-command'],
                         default='sshfs',
                         metavar='CMD',
                         required=True,
                         show_default=True,
                         help='command to mount sshfs filesystem',
                         ),
            click.Option(['--host'],
                         required=True,
                         metavar='HOST',
                         help='host to mount',
                         ),
            click.Option(['--path'],
                         help='path on target host to mount'),
            click.Option(['--ssh-user'],
                         metavar='USER',
                         help='user name to log on to target host',
                         ),
            click.Option(['--ssh-identity'],
                         metavar='PATH',
                         help='path to private key file to use for authentication',
                         ),
            click.Option(['--pwprompt'], is_flag=True,
                         help='prompt for password that will be used for authentication'),
            click.Option(['--mount-options'],
                         metavar='OPT1,OPT2,...',
                         help='additional options to be passed to sshfs command directly'),
        ]
