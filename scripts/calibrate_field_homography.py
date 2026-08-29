# -*- coding: utf-8 -*-
"""场地单应性标定（M0，图像四角 ↔ 场地坐标）。

操作步骤：
1. 地面按顺时针贴四个标记（西北/东北/东南/西南角），卷尺量出
   场地宽 W、高 H（米），西南角为原点（x 东 y 北）
2. 运行脚本，按提示依次点击四个角（图像窗口内鼠标点击），
   顺序必须与上述一致
3. 输出 .npz 单应性文件，供 drift camera/start 使用

用法：
    python scripts/calibrate_field_homography.py --camera 0 \
        --field-width 2.0 --field-height 2.0 --out field_homography.npz
"""
import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

PROMPTS = ["点击【西北角】（图像左上对应场地）", "点击【东北角】",
           "点击【东南角】", "点击【西南角】（场地原点）"]


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
    state = {"frame": None}

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and len(clicked) < 4:
            clicked.append((x, y))

    cv2.namedWindow("homography", cv2.WINDOW_NORMAL)
    cv2.setMouseCallback("homography", on_mouse)

    print("确认四角标记均在画面内后依次点击；r 键重置，ESC 完成")
    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        state["frame"] = frame
        for i, (px, py) in enumerate(clicked):
            cv2.circle(frame, (px, py), 8, (0, 0, 255), 2)
            cv2.putText(frame, str(i + 1), (px + 10, py - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        prompt = PROMPTS[len(clicked)] if len(clicked) < 4 else "已完成四点，ESC 保存退出"
        cv2.putText(frame, prompt, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        cv2.imshow("homography", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("r"):
            clicked.clear()
        if key == 27 and len(clicked) == 4:
            break
    cv2.destroyAllWindows()
    cap.release()

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
