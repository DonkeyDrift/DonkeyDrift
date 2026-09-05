# -*- coding: utf-8 -*-
"""场地单应性标定（M0，图像四角 ↔ 场地坐标）。

操作步骤：
1. 地面按顺时针贴四个标记（西北/东北/东南/西南角），卷尺量出
   场地宽 W、高 H（米），西南角为原点（x 东 y 北）
2. 运行脚本，按提示依次点击四个角（图像窗口内鼠标点击），
   顺序必须与上述一致；r 键重置，ESC 随时退出（满 4 点才保存）
3. 输出 .npz 单应性文件，供 drift camera/start 使用

用法：
    python scripts/calibrate_field_homography.py --camera 0 \
        --field-width 2.0 --field-height 2.0 --out field_homography.npz
"""
import argparse
from pathlib import Path

import cv2
import numpy as np

# cv2.putText 仅支持 ASCII：屏幕提示必须用英文（中文会渲染为 ???），
# 详细操作步骤在控制台以中文 print
PROMPTS = ["Click NW corner (image top-left)",
           "Click NE corner (image top-right)",
           "Click SE corner (image bottom-right)",
           "Click SW corner (field origin)"]


def main() -> int:
    parser = argparse.ArgumentParser(description="场地单应性标定（四点）")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--field-width", type=float, required=True, help="场地宽（米，x 方向）")
    parser.add_argument("--field-height", type=float, required=True, help="场地高（米，y 方向）")
    parser.add_argument("--out", default="field_homography.npz")
    args = parser.parse_args()

    cap = cv2.VideoCapture(args.camera, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    if not cap.isOpened():
        print(f"无法打开相机 index={args.camera}")
        return 1

    # 图像四角（NW, NE, SE, SW）↔ 场地四角（x 东 y 北：NW=(0,H) NE=(W,H) SE=(W,0) SW=(0,0)）
    field_pts = np.float32([
        [0.0, args.field_height], [args.field_width, args.field_height],
        [args.field_width, 0.0], [0.0, 0.0]])

    clicked = []

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and len(clicked) < 4:
            clicked.append((x, y))

    cv2.namedWindow("homography", cv2.WINDOW_NORMAL)
    cv2.setMouseCallback("homography", on_mouse)

    print("确认四角标记均在画面内后，按顺序点击：西北角 → 东北角 → 东南角 → 西南角（场地原点）")
    print("点错可按 r 键重置；ESC 随时退出——凑满 4 点才保存，未满不保存")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                continue
            for i, (px, py) in enumerate(clicked):
                cv2.circle(frame, (px, py), 8, (0, 0, 255), 2)
                cv2.putText(frame, str(i + 1), (px + 10, py - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
            prompt = (PROMPTS[len(clicked)] if len(clicked) < 4
                      else "4 points set - ESC to save & exit, R to reset")
            cv2.putText(frame, prompt, (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                        0.8, (0, 255, 0), 2)
            cv2.imshow("homography", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("r"):
                clicked.clear()
            elif key == 27:  # ESC：任何时刻都可退出
                break
    finally:
        cv2.destroyAllWindows()
        cap.release()

    if len(clicked) < 4:
        print(f"仅点击 {len(clicked)}/4 点，未保存：请重新运行并凑满四点")
        return 1

    image_pts = np.float32(clicked)
    h, _ = cv2.findHomography(image_pts, field_pts)
    if h is None:
        print("单应性求解失败：四点退化（共线/重合），请重标")
        return 1

    np.savez(args.out, h=h, field_width=args.field_width,
             field_height=args.field_height)
    print(f"单应性已保存：{Path(args.out).resolve()}")
    print("验证建议：把车放在已知场地坐标处，比对 drift 状态页的 pose 读数")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
