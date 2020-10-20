'''
Unit tests for name formatters
'''

from ..name_helpers import FileNameFormatter

def test_formatter_default_format():
    '''
    test default formatter behavior
    '''
    unq = FileNameFormatter()

    assert unq.format('abc') == 'abc'
    assert unq.format('abc') == 'abc-1'

def test_formatter_custom_format():
    '''
    test formatter with extension added
    '''
    unq = FileNameFormatter("-%03d", ".eml")

    assert unq.format('abc') == 'abc.eml'
    assert unq.format('abc') == 'abc-001.eml'
