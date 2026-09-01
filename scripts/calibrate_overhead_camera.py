# -*- coding: utf-8 -*-
"""俯拍相机内参标定（M0，棋盘格流程）。

操作步骤：
1. 打印棋盘格（默认 9×6 内角点，格距实测后 --square 填真实米数）
2. 相机架好后运行本脚本，手持棋盘格在画面各区域倾斜移动，
   每姿态按【空格】采集，采满 15 张按【ESC/回车】结束
3. 输出 calibration_intrinsics.npz（内参矩阵 + 畸变系数）

用法：
    python scripts/calibrate_overhead_camera.py --camera 0 [--square 0.025] \
        [--cols 9] [--rows 6] [--out calibration_intrinsics.npz]
"""
import argparse
from pathlib import Path

import cv2
import numpy as np

CHECKERBOARD_FLAGS = cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_FAST_CHECK | cv2.CALIB_CB_NORMALIZE_IMAGE


def main() -> int:
    parser = argparse.ArgumentParser(description="俯拍相机内参标定（棋盘格）")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--square", type=float, default=0.025, help="格距（米），务必实测")
    parser.add_argument("--cols", type=int, default=9, help="内角点列数")
    parser.add_argument("--rows", type=int, default=6, help="内角点行数")
    parser.add_argument("--min-images", type=int, default=15)
    parser.add_argument("--out", default="calibration_intrinsics.npz")
    args = parser.parse_args()

    cap = cv2.VideoCapture(args.camera, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    cap.set(cv2.CAP_PROP_FPS, args.fps)
    if not cap.isOpened():
        print(f"无法打开相机 index={args.camera}")
        return 1

    objp = np.zeros((args.rows * args.cols, 3), np.float32)
    objp[:, :2] = np.mgrid[0:args.cols, 0:args.rows].T.reshape(-1, 2) * args.square
    obj_points, img_points = [], []
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-4)

    print(f"手持棋盘格（{args.cols}×{args.rows} 内角点，格距 {args.square*1000:.0f}mm）"
          f"在画面各区域改变姿态，空格采集（目标 ≥{args.min_images} 张），ESC/回车结束并求解")
    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        found, corners = cv2.findChessboardCorners(gray, (args.cols, args.rows),
                                                   CHECKERBOARD_FLAGS)
        display = frame.copy()
        if found:
            corners_refined = cv2.cornerSubPix(
                gray, corners, (11, 11), (-1, -1), criteria)
            cv2.drawChessboardCorners(display, (args.cols, args.rows),
                                      corners_refined, found)
        cv2.putText(display, f"captured: {len(img_points)}  [SPACE=capture ESC/ENTER=finish]",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                    (0, 255, 0) if found else (0, 0, 255), 2)
        cv2.imshow("calibrate", display)
        key = cv2.waitKey(1) & 0xFF
        if key == 27 or key == 13:  # ESC 或回车结束（与文档一致）
            break
        if key == ord(" ") and found:
            obj_points.append(objp.copy())
            img_points.append(corners_refined)
    cv2.destroyAllWindows()
    cap.release()

    if len(img_points) < args.min_images:
        print(f"采集不足（{len(img_points)}/{args.min_images}），请重新标定")
        return 1

    ret, camera_matrix, dist_coeffs, _, _ = cv2.calibrateCamera(
        obj_points, img_points, gray.shape[::-1], None, None)
    print(f"重投影误差 RMS = {ret:.3f}px（<0.5 为佳）")
    np.savez(args.out, camera_matrix=camera_matrix, dist_coeffs=dist_coeffs,
             rms=ret)
    print(f"内参已保存：{Path(args.out).resolve()}")
    return 0 if ret < 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
