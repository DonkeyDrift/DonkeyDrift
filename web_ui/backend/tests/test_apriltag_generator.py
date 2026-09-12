# -*- coding: utf-8 -*-
"""tag36h11 打印件生成器测试。

核心风险是位序/镜像弄反导致打印出的标签解码错误，因此除结构断言外，
用 pupil_apriltags（官方 apriltag C 库移植）作为金标准做闭环验证。
"""
import sys
from pathlib import Path

import numpy as np
import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from generate_apriltag import (  # noqa: E402
    BIT_X,
    BIT_Y,
    BLACK,
    WHITE,
    load_codes,
    render_tag_grid,
    tag_module_grid,
)

CODES_PATH = SCRIPTS_DIR / "data" / "tag36h11_codes.txt"

pupil = pytest.importorskip("pupil_apriltags")


# ------------------------------------------------------------------
# 码表
# ------------------------------------------------------------------
def test_load_codes_returns_official_family():
    codes = load_codes(CODES_PATH)
    # tag36h11 官方家族共 587 个有效 ID
    assert len(codes) == 587
    # 与官方 tag36h11.c 首四个码字比对（gh api 拉取的源文件）
    assert codes[:4] == [
        0x0000000D7E00984B,
        0x0000000DDA664CA7,
        0x0000000DC4A1C821,
        0x0000000E17B470E9,
    ]


# ------------------------------------------------------------------
# 模块布局结构
# ------------------------------------------------------------------
def test_module_grid_has_quiet_border_and_data_region():
    grid = tag_module_grid(codes := load_codes(CODES_PATH)[0])  # noqa: F841
    # 总 10×10：外 1 模块白 quiet + 1 模块黑边框 + 6×6 数据
    assert len(grid) == 10 and all(len(row) == 10 for row in grid)
    # 外圈全白（quiet zone）
    assert all(grid[0][j] == WHITE for j in range(10))
    assert all(grid[9][j] == WHITE for j in range(10))
    assert all(grid[i][0] == WHITE for i in range(10))
    assert all(grid[i][9] == WHITE for i in range(10))
    # 黑边框圈全黑
    assert all(grid[1][j] == BLACK for j in range(1, 9))
    assert all(grid[8][j] == BLACK for j in range(1, 9))
    assert all(grid[i][1] == BLACK for i in range(1, 9))
    assert all(grid[i][8] == BLACK for i in range(1, 9))


def test_data_bits_follow_official_spiral_layout():
    """官方解码顺序为螺旋位序（tag36h11.c 的 bit_x/bit_y），
    且码字 bit=1 对应白模块（apriltag.c 中 v>0 即白色置 1）。"""
    code = load_codes(CODES_PATH)[0]
    grid = tag_module_grid(code)
    for i in range(36):
        white_bit = (code >> (35 - i)) & 1
        expected_black = 1 - white_bit
        got = grid[1 + BIT_Y[i]][1 + BIT_X[i]]
        assert got == expected_black, f"第 {i} 位（x={BIT_X[i]},y={BIT_Y[i]}）不符"


# ------------------------------------------------------------------
# 金标准：官方检测器解码闭环（防位序/镜像错误）
# ------------------------------------------------------------------
@pytest.mark.parametrize("tag_id", [0, 1])
def test_generated_tag_decodes_with_official_detector(tag_id):
    from pupil_apriltags import Detector

    codes = load_codes(CODES_PATH)
    image = render_tag_grid(codes[tag_id], pixels_per_module=40)
    detector = Detector(families="tag36h11", nthreads=1)
    results = detector.detect(image.astype(np.uint8))
    assert len(results) == 1, f"应恰好检出 1 个标签，实际 {len(results)}"
    assert results[0].tag_id == tag_id
    assert results[0].hamming == 0
