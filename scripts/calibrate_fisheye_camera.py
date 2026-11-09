# -*- coding: utf-8 -*-
"""鱼眼主摄像头内参标定（棋盘格流程，等距模型）。

生成的标定文件可被 donkeycar 的 FISHEYE 图像变换使用，
使"鱼眼展平"由粗略估算升级为精确去畸变。

操作步骤：
1. 打印棋盘格（默认 9×6 内角点，格距实测后 --square 填真实米数）
2. 相机架到实车实际位置与分辨率，手持棋盘格在画面各区域倾斜移动，
   每姿态按【空格】采集，采满 15 张按【ESC/回车】结束求解
3. 输出 fisheye_intrinsics.npz（camera_matrix / dist_coeffs / image_size / rms）

用法：
    python scripts/calibrate_fisheye_camera.py --camera 0 [--width 320 --height 240] \
        [--square 0.025] [--cols 9] [--rows 6] [--out mycar/fisheye_intrinsics.npz]

注意：标定分辨率应与实车 IMAGE_W×IMAGE_H 一致；若不一致，变换会按比例缩放内参并给出告警。
"""
import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

CHECKERBOARD_FLAGS = (cv2.CALIB_CB_ADAPTIVE_THRESH
                      | cv2.CALIB_CB_FAST_CHECK
                      | cv2.CALIB_CB_NORMALIZE_IMAGE)

FISHEYE_FLAGS = cv2.fisheye.CALIB_RECOMPUTE_EXTRINSIC | cv2.fisheye.CALIB_FIX_SKEW


def gui_available() -> bool:
    """判断当前 OpenCV 是否为带 GUI 的构建（headless 构建无法显示窗口）。"""
    try:
        for line in cv2.getBuildInformation().splitlines():
            if line.strip().startswith("GUI:"):
                return "NONE" not in line.upper()
    except Exception:
        pass
    return False


def open_camera(index, width, height, fps):
    """按平台选择后端打开相机（DSHOW 仅 Windows 可用，Linux 用 V4L2）。"""
    if sys.platform.startswith("win"):
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    elif sys.platform.startswith("linux"):
        cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
    else:
        cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        return cap
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)
    return cap


def main() -> int:
    parser = argparse.ArgumentParser(description="鱼眼主摄像头内参标定（棋盘格，等距模型）")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--width", type=int, default=320, help="应与实车 IMAGE_W 一致")
    parser.add_argument("--height", type=int, default=240, help="应与实车 IMAGE_H 一致")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--square", type=float, default=0.025, help="格距（米），务必实测")
    parser.add_argument("--cols", type=int, default=9, help="内角点列数")
    parser.add_argument("--rows", type=int, default=6, help="内角点行数")
    parser.add_argument("--min-images", type=int, default=15)
    parser.add_argument("--out", default="fisheye_intrinsics.npz")
    args = parser.parse_args()

    if not gui_available():
        print("当前 OpenCV 为无 GUI 构建（headless），无法弹出预览窗口，标定需要实时预览。\n"
              "请改装带 GUI 的同版本构建后重试，例如：\n"
              "    uv pip uninstall opencv-python-headless\n"
              "    uv pip install --no-deps opencv-python==4.11.0.86\n"
              "（--no-deps 用于避免改动已锁定的 numpy 1.26.4）")
        return 1

    cap = open_camera(args.camera, args.width, args.height, args.fps)
    if not cap.isOpened():
        print(f"无法打开相机 index={args.camera}（可用 `v4l2-ctl --list-devices` 或 "
              f"`ls /dev/video*` 确认设备号）")
        return 1

    objp = np.zeros((1, args.rows * args.cols, 3), np.float64)
    objp[0, :, :2] = np.mgrid[0:args.cols, 0:args.rows].T.reshape(-1, 2) * args.square
    obj_points, img_points = [], []
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-4)
    image_size = (0, 0)
    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if (actual_w, actual_h) != (args.width, args.height):
        print(f"注意：请求 {args.width}x{args.height}，相机实际输出 {actual_w}x{actual_h}；"
              f"将以实际分辨率标定（请确保与实车 IMAGE_W/IMAGE_H 一致）")

    print(f"手持棋盘格（{args.cols}×{args.rows} 内角点，格距 {args.square*1000:.0f}mm）"
          f"在画面各区域改变姿态，空格采集（目标 ≥{args.min_images} 张），ESC/回车结束并求解")
    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        image_size = gray.shape[::-1]
        found, corners = cv2.findChessboardCorners(gray, (args.cols, args.rows),
                                                   CHECKERBOARD_FLAGS)
        display = frame.copy()
        if found:
            corners_refined = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
            cv2.drawChessboardCorners(display, (args.cols, args.rows), corners_refined, found)
        cv2.putText(display, f"captured: {len(img_points)}  [SPACE=capture ESC/ENTER=finish]",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                    (0, 255, 0) if found else (0, 0, 255), 2)
        cv2.imshow("calibrate fisheye", display)
        key = cv2.waitKey(1) & 0xFF
        if key == 27 or key == 13:  # ESC 或回车结束
            break
        if key == ord(" ") and found:
            obj_points.append(objp.copy())
            img_points.append(corners_refined.reshape(1, -1, 2).astype(np.float64))
    cv2.destroyAllWindows()
    cap.release()

    if len(img_points) < args.min_images:
        print(f"采集不足（{len(img_points)}/{args.min_images}），请重新标定")
        return 1

    K = np.eye(3, dtype=np.float64)
    D = np.zeros((4, 1), dtype=np.float64)
    rms, K, D, _, _ = cv2.fisheye.calibrate(
        obj_points, img_points, image_size, K, D, flags=FISHEYE_FLAGS, criteria=criteria)
    print(f"重投影误差 RMS = {rms:.3f}px（<0.5 为佳）")
    np.savez(args.out, camera_matrix=K, dist_coeffs=D, image_size=np.array(image_size),
             rms=rms)
    print(f"鱼眼内参已保存：{Path(args.out).resolve()}")
    return 0 if rms < 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
