# -*- coding: utf-8 -*-
# Copyright (c) 2016, French National Center for Scientific Research (CNRS)
# Distributed under the (new) BSD License. See LICENSE for more info.

import numpy as np
import datetime
import pytest

from teleprox.serializer import JsonSerializer, MsgpackSerializer, HAVE_MSGPACK
from teleprox import start_process

class CustomType:
    def __init__(self):
        self.x = 1
        self.y = 'a'
    def __eq__(self, a):
        return type(a) == type(self) and a.x == self.x and a.y == self.y


@pytest.fixture(scope='module')
def test_data():
    proc = start_process('test_serializer_fixture_process')
    test_data = {
        'int': 1,
        'float': 1.,
        'str': 'abc',
        'bytes': b'abc',
        'ndarray': np.arange(8).reshape(2, 4).astype('float64'),
        'datetime': datetime.datetime(2015, 1, 1, 12, 00, 00),
        'date': datetime.date(2015, 1, 1),
        #'tuple': (1,2),  # both msgpack and json return tuples as lists.
                        # see: https://github.com/msgpack/msgpack-python/issues/98
        'list': [1,2],
        'proxy': proc.client['self'],
        # 'custom': CustomType(),  # TODO needs server
    }
    yield test_data

    proc.stop()


# pickle serializer currently doesn't exist..
# @pytest.mark.skip
# def test_pickle(test_data):
#     check_serializer(PickleSerializer(), test_data)

@pytest.mark.skipif(not HAVE_MSGPACK, reason='msgpack not available')
def test_msgpack(test_data):
    check_serializer(MsgpackSerializer(), test_data)

def test_json(test_data):
    check_serializer(JsonSerializer(), test_data)


def check_serializer(serializer, test_data):
    s = serializer.dumps(test_data, server=None, serialize_types=None)
    d2 = serializer.loads(s, server=None, proxy_opts=None)
    for k in test_data:
        v1 = test_data[k]
        v2 = d2[k]
        assert type(v1) is type(v2)
        if k == 'ndarray':
            assert np.all(v1 == v2)
        else:
            assert v1 == v2
