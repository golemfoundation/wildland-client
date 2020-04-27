# Wildland Project
#
# Copyright (C) 2020 Golem Foundation,
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

'''
Logging
'''

import logging.config


def init_logging(console=True, file_path=None):
    '''
    Configure logging module.
    '''

    config = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'default': {
                'class': 'logging.Formatter',
                'format': '%(asctime)s %(levelname)s [%(name)s] %(message)s',
            },
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'stream': 'ext://sys.stderr',
                'formatter': 'default',
            },
        },
        'root': {
            'level': 'DEBUG',
            'handlers': [],
        },
        'loggers': {
            'gnupg': {'level': 'INFO'},
            'boto3': {'level': 'INFO'},
            'botocore': {'level': 'INFO'},
            's3transfer': {'level': 'INFO'},
        }
    }


    if console:
        config['root']['handlers'].append('console')

    if file_path:
        config['handlers']['file'] = {
            'class': 'logging.FileHandler',
            'filename': file_path,
            'formatter': 'default',
        }
        config['root']['handlers'].append('file')
    logging.config.dictConfig(config)
