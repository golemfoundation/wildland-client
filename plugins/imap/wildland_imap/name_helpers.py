'''
The module provides various name formatter classes, which
can be used to format filenames materialized at various
places of the imap filesystem.
'''

from .TimelineDate import DatePart, TimelineDate

class FileNameFormatter:
    '''
    FileNameFormatter is a helper ensuring that uniqiufying
    suffixes will be added to the same names within the single
    directory. Suffixes are computed using occurrence count
    and formatted according to format passed as an contstructor
    argument.
    '''

    def __init__(self, counter_fmt: str = "-%d",
                 ext: str = ""):
        self._name_cnt = dict()
        self._fmt = counter_fmt
        self._ext = ext


    def format(self, name: str) -> str:
        '''
        return a formatted name for given email name. This can optionally
        append a counter suffix to disambiguate multiple emails with
        same sender and subject.
        '''
        if name in self._name_cnt:
            self._name_cnt[name] += 1
            rv = name + self._fmt % self._name_cnt[name] + self._ext
        else:
            self._name_cnt[name] = 0
            rv = name + self._ext
        return rv


class TimelineFormatter:
    '''
    A name formatter used to format timeline path elements.
    '''

    def __init__(self, level: DatePart):
        self._level = level

    def format(self, elt: TimelineDate) -> str:
        '''
        return a formatted file name representing
        given timeline element
        '''
        if self._level == DatePart.YEAR:
            # we render YEARS this way
            rv = '%04d' % elt.last_defined_value
        elif self._level == DatePart.MONTH:
            # that's how we render MONTHS
            rv = '%02d' % elt.last_defined_value
        else:
            # this is the format used for DAYS
            rv = '%02d' % elt.last_defined_value
        return rv
