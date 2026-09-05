# -*- coding: utf-8 -*-
"""tag36h11 AprilTag 可打印文件生成器。

用途：为俯拍漂移方案（RFC 8.1 车顶主标签）生成高分辨率打印件。
- 码表与位坐标来自官方 tag36h11.c：数据位按螺旋序排布（BIT_X/BIT_Y），
  码字 bit=1 对应白模块（apriltag.c 解码中 v>0 的白色位才置 1）
- 布局：10×10 模块 = 1 白 quiet 圈 + 1 黑边框圈 + 6×6 数据位
  （tag 本体指黑边框外缘，8 模块见方）
- 输出 A4 PDF（含 100mm 自检标尺）与 PNG，均按物理尺寸渲染
- --verify 用 pupil_apriltags（官方库移植）解码闭环自检

用法:
    python scripts/generate_apriltag.py                 # 生成 ID 0/1 打印件
    python scripts/generate_apriltag.py --ids 0 --tag-mm 80
    python scripts/generate_apriltag.py --verify        # 仅跑解码自检
"""
import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

WHITE = 0  # 模块网格中的白
BLACK = 1  # 模块网格中的黑

DATA_BITS = 36      # tag36h11: 6×6 数据位
DATA_SPAN = 6
QUIET_MODULES = 1   # tag 本体外的白边（图像内）
TOTAL_SPAN = DATA_SPAN + 2 + 2 * QUIET_MODULES  # 10 模块

# 官方螺旋位序：第 i 位（MSB=i:0）落在数据区 (BIT_X[i], BIT_Y[i])，
# 坐标 1~6。逐字抄录自 AprilRobotics/apriltag tag36h11.c 的
# tag36h11_create()，不得改动——位序错误会导致打印件无法解码。
BIT_X = (1, 2, 3, 4, 5, 2, 3, 4, 3, 6, 6, 6, 6, 6, 5, 5, 5, 4,
         6, 5, 4, 3, 2, 5, 4, 3, 4, 1, 1, 1, 1, 1, 2, 2, 2, 3)
BIT_Y = (1, 1, 1, 1, 1, 2, 2, 2, 3, 1, 2, 3, 4, 5, 2, 3, 4, 3,
         6, 6, 6, 6, 6, 5, 5, 5, 4, 6, 5, 4, 3, 2, 5, 4, 3, 4)

DPI = 600
A4_MM = (210.0, 297.0)


def load_codes(path: Path) -> list:
    """读取官方码表文件（每行一个 16 位十六进制码字）。"""
    text = Path(path).read_text(encoding="ascii").split()
    return [int(token, 16) for token in text]


def tag_module_grid(code: int) -> list:
    """把 36bit 码字铺成 10×10 模块网格（1=黑 0=白）。

    外圈白 quiet、次圈黑边框、内部 6×6 数据按官方螺旋位序；
    码字 bit=1 → 白模块，bit=0 → 黑模块。
    """
    grid = [[WHITE] * TOTAL_SPAN for _ in range(TOTAL_SPAN)]
    for k in range(1, TOTAL_SPAN - 1):  # 黑边框圈
        grid[1][k] = BLACK
        grid[TOTAL_SPAN - 2][k] = BLACK
        grid[k][1] = BLACK
        grid[k][TOTAL_SPAN - 2] = BLACK
    for i in range(DATA_BITS):  # 数据位（螺旋序，MSB=第 0 位）
        white_bit = (code >> (DATA_BITS - 1 - i)) & 1
        grid[1 + BIT_Y[i]][1 + BIT_X[i]] = 1 - white_bit
    return grid


def render_tag_grid(code: int, pixels_per_module: int) -> np.ndarray:
    """渲染为灰度图像（黑=0，白=255），四周各 1 模块白边。"""
    grid = tag_module_grid(code)
    size = TOTAL_SPAN * pixels_per_module
    image = np.full((size, size), 255, dtype=np.uint8)
    for i in range(TOTAL_SPAN):
        for j in range(TOTAL_SPAN):
            if grid[i][j] == BLACK:
                image[
                    i * pixels_per_module:(i + 1) * pixels_per_module,
                    j * pixels_per_module:(j + 1) * pixels_per_module,
                ] = 0
    return image


# ------------------------------------------------------------------
# 打印页渲染
# ------------------------------------------------------------------
def _mm_to_px(mm: float) -> int:
    return round(mm / 25.4 * DPI)


def _load_font(size_px: int) -> ImageFont.FreeTypeFont:
    for candidate in (
        r"C:\Windows\Fonts\msyh.ttc",    # 微软雅黑（中文）
        r"C:\Windows\Fonts\arial.ttf",
    ):
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size_px)
    return ImageFont.load_default()


def render_a4_page(tag_id: int, code: int, tag_body_mm: float) -> Image.Image:
    """渲染 A4 单页：居中标签 + 100mm 自检标尺 + 打印注意事项。"""
    page_w, page_h = _mm_to_px(A4_MM[0]), _mm_to_px(A4_MM[1])
    page = Image.new("L", (page_w, page_h), 255)
    draw = ImageDraw.Draw(page)

    # 标签（含 quiet 共 10 模块），水平居中、垂直略偏上
    pixels_per_module = _mm_to_px(tag_body_mm / 8.0)
    tag_px = render_tag_grid(code, pixels_per_module)
    tag_x = (page_w - tag_px.shape[1]) // 2
    tag_y = _mm_to_px(45)
    page.paste(Image.fromarray(tag_px), (tag_x, tag_y))
    tag_bottom = tag_y + tag_px.shape[0]

    # 100mm 自检标尺（打印后实测：应恰为 100.0mm，否则打印机缩放了）
    ruler_y = tag_bottom + _mm_to_px(18)
    ruler_half = _mm_to_px(50)
    cx = page_w // 2
    line_w = max(2, _mm_to_px(0.3))
    draw.line(
        [(cx - ruler_half, ruler_y), (cx + ruler_half, ruler_y)],
        fill=0, width=line_w,
    )
    for x0 in (cx - ruler_half, cx + ruler_half):
        draw.line(
            [(x0, ruler_y - _mm_to_px(3)), (x0, ruler_y + _mm_to_px(3))],
            fill=0, width=line_w,
        )

    # 注记文字
    note_font = _load_font(_mm_to_px(4.2))
    lines = [
        f"tag36h11 · ID {tag_id} · 黑框本体 {tag_body_mm:.0f} mm",
        "打印设置：100% 实际大小（不要“适合页面”），打印后实测上方标尺=100mm、黑框=所标尺寸",
        f"回填车端配置：tag_family=tag36h11 tag_id={tag_id} tag_size_m={tag_body_mm / 1000.0}",
    ]
    text_y = ruler_y + _mm_to_px(12)
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=note_font)
        draw.text(((page_w - (bbox[2] - bbox[0])) // 2, text_y), line,
                  fill=0, font=note_font)
        text_y += _mm_to_px(8)
    return page


def main() -> int:
    parser = argparse.ArgumentParser(description="tag36h11 打印件生成器")
    parser.add_argument("--ids", type=int, nargs="+", default=[0, 1],
                        help="要生成的标签 ID（默认 0 1）")
    parser.add_argument("--tag-mm", type=float, default=80.0,
                        help="黑框本体边长毫米（默认 80）")
    parser.add_argument("--out", default="docs/assets/apriltags",
                        help="输出目录")
    parser.add_argument("--verify", action="store_true",
                        help="只跑官方检测器解码自检，不写打印件")
    args = parser.parse_args()

    codes_path = Path(__file__).parent / "data" / "tag36h11_codes.txt"
    codes = load_codes(codes_path)
    if len(codes) != 587:
        print(f"码表异常：{len(codes)} 项（应为 587）", file=sys.stderr)
        return 1
    for tag_id in args.ids:
        if not 0 <= tag_id < len(codes):
            print(f"ID {tag_id} 超出家族范围 0~{len(codes) - 1}", file=sys.stderr)
            return 1

    if args.verify:  # 解码闭环：官方库必须解出正确 ID
        from pupil_apriltags import Detector
        detector = Detector(families="tag36h11", nthreads=1)
        for tag_id in args.ids:
            image = render_tag_grid(codes[tag_id], pixels_per_module=40)
            results = detector.detect(image)
            ok = len(results) == 1 and results[0].tag_id == tag_id
            print(f"ID {tag_id}: {'解码通过' if ok else '解码失败'}")
            if not ok:
                return 1
        return 0

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    pages = []
    for tag_id in args.ids:
        page = render_a4_page(tag_id, codes[tag_id], args.tag_mm)
        pages.append(page)
        page.save(out_dir / f"tag36h11_id{tag_id}_{int(args.tag_mm)}mm.png",
                  dpi=(DPI, DPI))
        # 纯标签裁剪版（贴车顶用，含 1 模块白边共 tag_mm*10/8）
        tag_only = Image.fromarray(
            render_tag_grid(codes[tag_id], _mm_to_px(args.tag_mm / 8.0)))
        tag_only.save(out_dir / f"tag36h11_id{tag_id}_tag_only.png",
                      dpi=(DPI, DPI))
        print(f"ID {tag_id} 页面与标签图已生成")
    pages[0].save(out_dir / f"tag36h11_print_{int(args.tag_mm)}mm.pdf",
                  "PDF", resolution=DPI,
                  save_all=True, append_images=pages[1:])
    print(f"PDF: {out_dir / f'tag36h11_print_{int(args.tag_mm)}mm.pdf'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
