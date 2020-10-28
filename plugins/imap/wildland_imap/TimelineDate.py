'''
This package contains a fuzzy wrapper for datetime objects. The fuzziness
here means that comparisson match with given accuracy (i.e. YEAR/MONTH/DAY)
'''

#pylint: disable=no-else-return

from enum import IntEnum
from datetime import datetime

class DatePart(IntEnum):
    '''
    Enumeration determining accuracy level / date part being looked at.
    '''
    EPOCH = 0
    YEAR = 1
    MONTH = 2
    DAY = 3

    def advance(self):
        '''
        advance to the next level of detail (i.e.
        DataPart.YEAR.advance() == DatePart.MONTH
        '''
        return DatePart(self + 1)

class TimelineDate:
    '''
    A representation of calendar date (YYYY-MM-DD) for the
    purpose of timeline operations.

    The objects of this type are constructed by passing
    standard python datetime object but provide some convenience
    methods for date parts extraction.
    '''

    def __init__(self, accuracy: DatePart = DatePart.EPOCH,
                 value: datetime = None):
        self.accuracy = accuracy
        if value is None:
            self.value = datetime.today()
        else:
            self.value = value
        vals = (self.value.year, self.value.month, self.value.day)
        if self.accuracy > 0:
            self.last_defined_value = vals[self.accuracy - 1]
        else:
            self.last_defined_value = None

    def up_to(self, accuracy: DatePart):
        '''
        returns a TimelineDate object based on the value of current object
        but constrained to different accuracy level.
        '''
        return TimelineDate(accuracy, self.value)

    def _value_of(self, part: DatePart) -> int:
        '''
        returns a numeric value of given date part
        '''
        vals = (0, self.value.year, self.value.month, self.value.day)
        return vals[part]

    def __repr__(self):
        return f'value={self.value}, accuracy={self.accuracy}'
    def _allvals(self):
        return (self.value.year, self.value.month, self.value.day)

    def __hash__(self):
        return hash(self._allvals()[:self.accuracy])

    def __eq__(self, other):
        return self._allvals()[:self.accuracy] == other._allvals()[:other.accuracy]
