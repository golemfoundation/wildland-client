# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
#                    Paweł Marczewski <pawel@invisiblethingslab.com>,
#                    Wojtek Porczyk <woju@invisiblethingslab.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Logging
"""

import os
import logging
import logging.config

from .exc import WildlandError

RootStreamHandler = logging.StreamHandler()


def get_logger(name):
    """
    Simple logger
    """
    logger = logging.getLogger(name)
    return logger


class ConsoleFormatter(logging.Formatter):
    """
    A formatter that colors messages in console.
    """

    default_time_format = '%H:%M:%S'
    # https://en.wikipedia.org/wiki/ANSI_escape_code
    colors = {
        'grey': '\x1b[38;5;246m',
        'green': '\x1b[32m',
        'yellow': '\x1b[93;1m',
        'red': '\x1b[91;1m',
        'cyan': '\x1b[96m',
        'reset': '\x1b[0m',
    }

    def __init__(self, fmt, *args, **kwargs):
        if fmt is None:
            fmt = ('{grey}%(asctime)s '
                   '{green}[%(process)d/%(threadName)s] '
                   '{cyan}[%(name)s] '
                   '$COLOR%(message)s'
                   '{reset}')
            fmt = fmt.format(**self.colors)
        super().__init__(fmt, *args, **kwargs)

    def format(self, record):
        result = super().format(record)
        level_color = {
            'DEBUG': 'grey',
            'INFO': 'reset',
            'WARNING': 'yellow',
            'ERROR': 'red',
            'CRITICAL': 'red',
        }.get(record.levelname, 'reset')
        result = result.replace('$COLOR', self.colors[level_color])
        return result

    def formatException(self, ei):
        result = super().formatException(ei)
        result = '{red}{result}{reset}'.format(result=result, **self.colors)
        return result


class BriefConsoleFormatter(ConsoleFormatter):
    """
    A formatter for color and brief (for users) messages in console.
    """
    colors = {
        'grey': '\x1b[38;5;246m',
        'green': '\x1b[32m',
        'yellow': '\x1b[33m',
        'red': '\x1b[31m',
        'cyan': '\x1b[36m',
        'reset': '\x1b[0m',
    }

    def __init__(self, fmt, *args, **kwargs):
        fmt = '%(message)s'
        fmt = fmt.format(**self.colors)
        super().__init__(fmt, *args, **kwargs)

    def format(self, record):
        result = super().format(record)
        result = result.replace('$LEVEL', record.levelname.title())
        return result


def init_logging(console=True, file_path=None, level='DEBUG'):
    """
    Configure logging module.
    """

    config: dict = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'default': {
                'class': 'logging.Formatter',
                'format': '%(asctime)s [%(process)d/%(threadName)s] %(levelname)s [%(name)s] '
                          '%(message)s',
            },
            'console': {
                'class': 'wildland.log.ConsoleFormatter',
            },
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'stream': 'ext://sys.stderr',
                'formatter': 'console',
            },
        },
        'root': {
            'level': level,
            'handlers': [],
        },
        'loggers': {
            'boto3': {'level': 'INFO'},
            'botocore': {'level': 'INFO'},
            's3transfer': {'level': 'INFO'},
        }
    }

    if console:
        config['root']['handlers'].append('console')

        if level not in ("DEBUG"):
            config['formatters']['console']['class'] = 'wildland.log.BriefConsoleFormatter'

    if file_path:
        config['handlers']['file'] = {
            'class': 'logging.FileHandler',
            'filename': file_path,
            'formatter': 'default',
        }
        config['root']['handlers'].append('file')

        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
        except OSError as e:
            raise WildlandError("Failed to initialize logging file") from e

    logging.config.dictConfig(config)

    if file_path:
        # logging does not provide a way to specify file permission
        os.chmod(file_path, 0o640)

    # fixme: is logging allowing handler instance inside dictConfig?
    root_logger = logging.getLogger()
    for h in root_logger.handlers:
        if h.name == "console":
            # pylint: disable=global-statement
            global RootStreamHandler
            RootStreamHandler = h  # type: ignore
            break
