'''
Tests for TimelineDate class.
'''

from datetime import datetime
from ..TimelineDate import TimelineDate, DatePart

def test_comparison():
    '''
    Test if comparison for equality / inequality is implemented
    correctly.
    '''
    t1 = TimelineDate()
    t2 = TimelineDate()
    assert t1 == t2
    d1 = datetime(1977, 7, 6)
    d2 = datetime(1977, 7, 7)
    assert TimelineDate(DatePart.YEAR, d1) == TimelineDate(DatePart.YEAR, d2)
    assert TimelineDate(DatePart.MONTH, d1) == TimelineDate(DatePart.MONTH, d2)
    assert TimelineDate(DatePart.DAY, d1) != TimelineDate(DatePart.DAY, d2)

    d3 = d2
    assert TimelineDate(DatePart.DAY, d3) == TimelineDate(DatePart.DAY, d2)
    assert TimelineDate(DatePart.YEAR, d3) != TimelineDate(DatePart.DAY, d3)
    assert TimelineDate(DatePart.YEAR, d3) == TimelineDate(DatePart.DAY, d3).up_to(DatePart.YEAR)
    assert TimelineDate(DatePart.YEAR, d3) != TimelineDate(DatePart.EPOCH, d3)
    assert TimelineDate(DatePart.EPOCH, d2) == TimelineDate(DatePart.EPOCH, d3)

def test_last_defined_value():
    '''
    Test if last_defined_value is set correctly according to accuracy.
    '''
    t1 = TimelineDate(DatePart.EPOCH, datetime(1977, 7, 6))
    t2 = TimelineDate(DatePart.YEAR, datetime(1977, 7, 6))
    t3 = TimelineDate(DatePart.MONTH, datetime(1977, 7, 6))
    t4 = TimelineDate(DatePart.DAY, datetime(1977, 7, 6))

    assert t1.last_defined_value is None
    assert t2.last_defined_value == 1977
    assert t3.last_defined_value == 7
    assert t4.last_defined_value == 6


def test_up_to():
    '''
    Test if up_to() call correctly limits accuracy.
    '''
    t1 = TimelineDate(DatePart.DAY, datetime(1977, 7, 6))

    assert t1.up_to(DatePart.DAY).last_defined_value == 6
    assert t1.up_to(DatePart.MONTH).last_defined_value == 7
    assert t1.up_to(DatePart.YEAR).last_defined_value == 1977
