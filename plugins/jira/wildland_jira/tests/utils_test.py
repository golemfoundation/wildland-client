# Wildland Project
#
# Copyright (C) 2021 Golem Foundation
#
# Authors:
#                 Dominik Gonciarz <dominik.gonciarz@besidethepark.com>
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
Unit tests for jira plugin utils
"""
from ..utils import stringify_query_params, encode_dict_to_jql


def test_stringify_query_params():
    args = {
        'empty': {},
        'single_str': {'orderBy': 'updated'},
        'multiple_str': {'orderBy': 'updated', 'after': 'b362hs2',
                         'jql': 'project=Personal OR project="jira extension"'},
        'single_list': {'fields': ['description', 'labels', 'project']},
        'parameters_list_mix': {'fields': ['description', 'labels', 'project'],
                                'expand': ['schema', 'names'], 'orderBy': 'updated',
                                'after': 'b362hs2', 'maxResults': 100},
    }
    expected = {
        'empty': '',
        'single_str': '?orderBy%3Dupdated',
        'multiple_str': '?orderBy%3Dupdated&after%3Db362hs2&jql%3Dproject%3DPersonal%20OR'
                        '%20project%3D%22jira%20extension%22',
        'single_list': '?fields%3Ddescription%2Clabels%2Cproject',
        'parameters_list_mix': '?fields%3Ddescription%2Clabels%2Cproject&expand%3Dschema%2C'
                               'names&orderBy%3Dupdated&after%3Db362hs2&maxResults%3D100',
    }
    for key in args:
        assert expected[key] == stringify_query_params(args[key])


def test_stringify_jql_dict():
    args = {
        'empty': {},
        'empty_order': {'order_by': 'assignee', 'order_dir': 'ASC'},
        'single_str': {'params': {'project': 'Personal'}},
        'multiple_str': {'params': {'project': 'Personal', 'assignee': 'b362hs2'}},
        'single_list': {'params': {'project': ['Personal', 'jira extension']}},
        'parameters_list_mix': {'params': {'project': ['Personal', 'jira extension'],
                                           'fields': ['description', 'labels', 'project'],
                                           'orderBy': 'updated',
                                           'after': 'b362hs2', 'maxResults': 100}}
    }
    expected = {
        'empty': '%20order%20by%20updatedDate%20DESC',
        'empty_order': '%20order%20by%20assignee%20ASC',
        'single_str': 'project%3D%22Personal%22%20order%20by%20updatedDate%20DESC',
        'multiple_str': 'project%3D%22Personal%22%20AND%20assignee%3D%22b362hs2%22%20order%20by'
                        '%20updatedDate%20DESC',
        'single_list': '%28project%3D%22Personal%22%20OR%20project%3D%22jira%20extension%22%29'
                       '%20order%20by%20updatedDate%20DESC',
        'parameters_list_mix': '%28project%3D%22Personal%22%20OR%20project%3D%22jira%20extension'
                               '%22%29%20AND%20%28fields%3D%22description%22%20OR%20fields%3D'
                               '%22labels%22%20OR%20fields%3D%22project%22%29%20AND%20orderBy%3D'
                               '%22updated%22%20AND%20after%3D%22b362hs2%22%20AND%20maxResults%3D'
                               '%22100%22%20order%20by%20updatedDate%20DESC'}

    for key in args:
        assert expected[key] == encode_dict_to_jql(args[key].get('params'),
                                                   order_by=args[key].get('order_by'),
                                                   order_dir=args[key].get('order_dir'))
