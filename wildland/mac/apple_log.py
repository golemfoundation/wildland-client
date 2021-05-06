# Wildland project
#
# Copyright (C) 2020 Golem Foundation,
#                    Piotr K. Isajew <piotr@wildland.io>
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
A simple configuration for Python logging system to divert all messages to
Apple's Unified Logging.
'''

# pylint: disable=import-error
import logging
from PBRLogBridge import log_message

class apple_log(logging.StreamHandler):
    '''
    A logging handler class which is responsible for forwarding
    log messages to the Apple unified logging logging bridge.
    '''

    def __init__(self):
        logging.StreamHandler.__init__(self)

    def emit(self, record):
        text = self.format(record)
        log_message(text)

    @staticmethod
    def configure():
        '''
        Configure the logging system to use the Apple
        logging bridge. This should be called before
        any log statements are executed.
        '''

        ioshandler = apple_log()
        logging.basicConfig(level=logging.DEBUG)
        logger = logging.getLogger()
        logger.handlers = [ ]
        logger.addHandler(ioshandler)
