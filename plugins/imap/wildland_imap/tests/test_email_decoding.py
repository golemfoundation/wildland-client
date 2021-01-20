'''
Unit tests for email decoding
'''
from ..ImapClient import _decode_text


def test_decode_nasty_subject():
    '''
    test if we can decode a nasty subject with a lot of quoted-printable
    entities in it.
    '''

    expected = 'GOLEM nie jest człowiekiem, więc nie ma ani osobowości, ani charakteru'
    inputs = [(b'GOLEM nie jest ', None), (b'cz\xc5\x82owiekiem', 'utf-8'),
              (b', wi\xc4\x99c nie ma ani osobowo\xc5\x9bci', 'utf-8'),
              (b', ani charakteru', None)]

    decoded = _decode_text(inputs)

    assert decoded == expected
