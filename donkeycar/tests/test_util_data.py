#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun Jun 25 14:17:59 2017

@author: wroscoe
"""
import unittest
import pytest


from donkeycar.utils import *


def create_lbin(marker_index):
    """ Create a linear binary array with value set """
    l = [0] * 15
    l[marker_index] = 1
    return l


class TestLinearBin(unittest.TestCase):

    def test_zero(self):
        res = linear_bin(0)
        assert res[7] == 1
        assert sum(res[:7]) == 0
        assert sum(res[8:]) == 0

    def test_positive(self):
        res = linear_bin(1)
        assert res[14] == 1
        assert sum(res[:14]) == 0

    def test_negative(self):
        res = linear_bin(-1)
        assert res[0] == 1
        assert sum(res[1:]) == 0

    def test_illegal_type(self):
        with pytest.raises(TypeError):
            linear_bin('0')


class TestLinearUnbin(unittest.TestCase):

    def test_zero(self):
        l = create_lbin(7)
        res = linear_unbin(l)
        assert res == 0.0

    def test_positive(self):
        l = create_lbin(14)
        res = linear_unbin(l)
        assert res == 1.0

    def test_negative(self):
        l = create_lbin(0)
        res = linear_unbin(l)
        assert res == -1.0

    def test_empty_list(self):
        res = linear_unbin( [0] * 15 )
        assert res == -1.0


class TestLinearUnbinSoftmax(unittest.TestCase):

    def test_one_hot_matches_linear_unbin(self):
        # 对 one-hot 输入，期望值解码退化为 argmax，结果应与 linear_unbin 一致
        for idx in (0, 7, 14):
            l = create_lbin(idx)
            assert linear_unbin_softmax(l) == linear_unbin(l)

    def test_uniform_distribution_returns_center(self):
        # 15 个 angle 分箱均匀分布 -> 期望 bin=7 -> 0.0
        arr = [1.0 / 15] * 15
        assert linear_unbin_softmax(arr) == pytest.approx(0.0)

    def test_skewed_distribution_returns_weighted_average(self):
        # 0.5 权重在最左(0)与最右(14) -> 期望 bin=7 -> 0.0
        arr = [0.0] * 15
        arr[0] = 0.5
        arr[14] = 0.5
        assert linear_unbin_softmax(arr) == pytest.approx(0.0)

    def test_throttle_expected_value(self):
        # 20 个 throttle 分箱均匀分布，R=0.5 offset=0 -> 期望 bin=9.5 -> 0.2375
        arr = [1.0 / 20] * 20
        assert linear_unbin_softmax(arr, N=20, offset=0.0, R=0.5) == \
            pytest.approx(0.2375)


class TestMapping(unittest.TestCase):

    def test_positive(self):
        min = map_range(-100, -100, 100, 0, 1000)
        half = map_range(0, -100, 100, 0, 1000)
        max = map_range(100, -100, 100, 0, 1000)
        assert min == 0
        assert half == 500
        assert max == 1000

    def test_negative(self):
        ranges = (0, 100, 0, 1000)
        min = map_range(0, *ranges)
        half = map_range(50, *ranges)
        max = map_range(100, *ranges)
        assert min == 0
        assert half == 500
        assert max == 1000

    def test_reverse(self):
        ranges = (100, 0, 0, 1000)
        min = map_range(0, *ranges)
        half = map_range(50, *ranges)
        max = map_range(100, *ranges)
        assert min == 1000
        assert half == 500
        assert max == 0


class TestMapRangeFloat(unittest.TestCase):

    def test_source_int_range(self):
        assert 0.0 == map_range_float(0, 0, 100, 0, 1.0)
        assert 0.5 == map_range_float(50, 0, 100, 0, 1.0)
        assert 1.0 == map_range_float(100, 0, 100, 0, 1.0)

        # Try a different range
        assert 0.0 == map_range_float(0, 0, 20, 0, 1.0)
        assert 0.25 == map_range_float(5, 0, 20, 0, 1.0)
        assert 0.5 == map_range_float(10, 0, 20, 0, 1.0)
        assert 0.75 == map_range_float(15, 0, 20, 0, 1.0)
        assert 1.0 == map_range_float(20, 0, 20, 0, 1.0)

    def test_source_float_range(self):
        assert 0.0 == map_range_float(0, 0, 1.0, 0, 1.0)
        assert 0.5 == map_range_float(0.5, 0, 1.0, 0, 1.0)
        assert 1.0 == map_range_float(1.0, 0, 1.0, 0, 1.0)
        assert 0.95 == map_range_float(0.95, 0, 1.0, 0, 1.0)

    def test_negative(self):
        assert 0.0 == map_range_float(0, -100, 100, -1.0, 1.0)
        assert -1.0 == map_range_float(-100, -100, 100, -1.0, 1.0)
        assert 1.0 == map_range_float(100, -100, 100, -1.0, 1.0)

    def test_scale_down(self):
        assert 0.0 == map_range_float(0, 0, 100, 0, 0.5)
        assert 0.25 == map_range_float(50, 0, 100, 0, 0.5)
        assert 0.5 == map_range_float(100, 0, 100, 0, 0.5)

    def test_scale_up(self):
        assert 0.0 == map_range_float(0, 0, 100, 0, 2.0)
        assert 1.0 == map_range_float(50, 0, 100, 0, 2.0)
        assert 2.0 == map_range_float(100, 0, 100, 0, 2.0)


class TestMergeDicts(unittest.TestCase):

    def test_merge_two_dicts(self):
        d1 = { 'a' : 1, 'b' : 2, 'c' : 3 }
        d2 = { 10 : 'hi', 'bob' : 20 }
        res = merge_two_dicts(d1, d2)

        assert res == { 'a' : 1, 'b' : 2, 'c' : 3, 10 : 'hi', 'bob' : 20 }

class TestParamGen(unittest.TestCase):

    def test_param_gen(self):
        g = param_gen({ 'a' : [ 'opt1', 'opt2' ], 'b' : [ 'opt3', 'opt4' ] })
        l = [ x for x in g ]
        expected = [
                {'a': 'opt1', 'b': 'opt3'},
                {'a': 'opt1', 'b': 'opt4'},
                {'a': 'opt2', 'b': 'opt3'},
                {'a': 'opt2', 'b': 'opt4'}
            ]
        self.assertCountEqual(expected, l)

def test_train_test_split():
    data_set = [1, 2, 3, 4, 5, 6, 7, 8, 9, 0]
    train_set, val_set = train_test_split(data_set, test_size=0.2)
    print(train_set)
    print(val_set)
    assert(len(train_set)==8)
    assert(len(val_set)==2)


def test_fit_pil_image_and_array_preserves_aspect_with_white_border():
    from PIL import Image
    import numpy as np

    # 1. Same aspect ratio (320x240 -> 160x120): proportional resize without borders
    im_43 = Image.new("RGB", (320, 240), (30, 60, 90))
    out_43 = np.asarray(fit_pil_image(im_43, 160, 120))
    assert out_43.shape == (120, 160, 3)
    assert np.all(out_43 == [30, 60, 90])

    # 2. Wider 16:9 (320x180 -> 160x120): 160x90 centered with 15px top/bottom white border
    arr_169 = np.full((180, 320, 3), 50, dtype=np.uint8)
    out_169 = fit_image_array(arr_169, 160, 120)
    assert out_169.shape == (120, 160, 3)
    assert np.all(out_169[:15, :, :] == 255)
    assert np.all(out_169[105:, :, :] == 255)
    assert np.all(out_169[15:105, :, :] == 50)

    # 3. Square 1:1 (96x96 -> 160x120): 120x120 centered with 20px left/right white border
    arr_sq = np.full((96, 96, 3), 80, dtype=np.uint8)
    out_sq = fit_image_array(arr_sq, 160, 120)
    assert out_sq.shape == (120, 160, 3)
    assert np.all(out_sq[:, :20, :] == 255)
    assert np.all(out_sq[:, 140:, :] == 255)
    assert np.all(out_sq[:, 20:140, :] == 80)

