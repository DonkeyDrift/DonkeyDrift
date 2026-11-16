# -*- coding: utf-8 -*-
"""鱼眼展平效果的离线验证：在一张真实鱼眼帧上对比不同设置的输出，生成拼图并打印指标。

用法：
    python scripts/verify_fisheye_undistort.py [--image path.jpg | --tub dir] \
        [--out docs/assets/fisheye_demo.png] [--scale 2]
"""
import argparse
import glob
import logging
import os
import types

import cv2
import numpy as np

from donkeycar.parts.fisheye import FisheyeUndistort, estimate_image_circle

logging.basicConfig(level=logging.WARNING)


def pick_image(args):
    if args.image:
        return args.image
    paths = sorted(glob.glob(os.path.join(args.tub, "*.jpg")))
    if not paths:
        raise SystemExit(f"{args.tub} 下没有找到 .jpg 图像")
    return paths[len(paths) // 2]


def label(panel, text, scale):
    cv2.rectangle(panel, (0, 0), (panel.shape[1], 26), (0, 0, 0), -1)
    cv2.putText(panel, text, (6, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 1,
                cv2.LINE_AA)
    return panel


def render(img, config_ns, scale):
    part = FisheyeUndistort(config_ns)
    out = part.run(img)
    info = f" hFOV={part.out_fov:.0f}deg  black={(cv2.cvtColor(out, cv2.COLOR_BGR2GRAY) < 20).mean() * 100:.1f}%"
    if scale != 1:
        out = cv2.resize(out, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
    return out, info


def main():
    parser = argparse.ArgumentParser(description="鱼眼展平效果离线验证")
    parser.add_argument("--image", help="单张鱼眼图路径")
    parser.add_argument("--tub", default="/home/dkc/projects/mycar/data/images",
                        help="tub 图像目录（自动取中间一帧）")
    parser.add_argument("--out", default="docs/assets/fisheye_demo.png")
    parser.add_argument("--scale", type=float, default=2.0)
    parser.add_argument("--fov-deg", type=float, default=160.0, help="估算模型的圆形 FOV")
    args = parser.parse_args()

    path = pick_image(args)
    img = cv2.imread(path)
    if img is None:
        raise SystemExit(f"无法读取图像: {path}")
    h, w = img.shape[:2]
    cx, cy, r = estimate_image_circle(img)
    print(f"图像: {path} ({w}x{h})")
    print(f"检测成像圆: 圆心=({cx:.0f},{cy:.0f}) 半径={r:.0f}")
    print(f"原始画面黑边占比: {(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) < 20).mean() * 100:.1f}%\n")

    base = dict(IMAGE_W=w, IMAGE_H=h, FISHEYE_FOV_DEG=args.fov_deg)
    variants = [
        ("auto max FOV", {}),
        ("FOV=120", {"FISHEYE_OUT_FOV_DEG": 120.0}),
        ("FOV=100", {"FISHEYE_OUT_FOV_DEG": 100.0}),
    ]

    panels = [label(img.copy(), f"original fisheye {w}x{h}", args.scale)]
    for name, extra in variants:
        cfg = types.SimpleNamespace(**{**base, **extra})
        out, info = render(img, cfg, int(args.scale))
        print(f"[{name:12}] 输出 {out.shape[1]//int(args.scale)}x{out.shape[0]//int(args.scale)}{info}")
        panels.append(label(out, name + info, args.scale))

    max_h = max(p.shape[0] for p in panels)
    panels = [cv2.copyMakeBorder(p, 0, max_h - p.shape[0], 0, 8, cv2.BORDER_CONSTANT,
                                 value=(40, 40, 40)) for p in panels]
    montage = np.hstack(panels)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    cv2.imwrite(args.out, montage)
    print(f"\n对比拼图已保存: {os.path.abspath(args.out)}")


if __name__ == "__main__":
    main()
