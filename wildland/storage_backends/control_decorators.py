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
Decorators for ControlStorage. Defined separately to avoid cyclic imports.
'''


def control_directory(name):
    '''Decorator for creating control directories

    Decorated generator should yield 2-tuples: name (a string) and object which
    represents the directory contents. That object's class should have further
    attributes decorated with either :func:`control_file` or
    :func:`control_directory`.
    '''
    assert '/' not in name

    def decorator(func):
        func._control_name = name
        func._control_read = False
        func._control_write = False
        func._control_directory = True
        return func

    return decorator

def control_file(name, *, read=True, write=False, json=False):
    '''Decorator for creating control files

    When the file is *read*, decorated function will be called without argument
    and should return the director contents (:class:`bytes`). When the file is
    *written*, the function will be called with the argument to ``write()``
    (also :class:`bytes`).

    Args:
        name (str): file name
        read (bool): if :obj:`True`, the file is readable
        write (bool): if :obj:`True`, the file is writable
        json (bool):  if :obj:`True`, the file accepts JSON commands
    '''
    assert '/' not in name
    assert read or write
    if json:
        assert write, 'json=True needs write=True'

    def decorator(func):
        func._control_name = name
        func._control_read = read
        func._control_write = write
        func._control_json = json
        func._control_directory = False
        return func

    return decorator
