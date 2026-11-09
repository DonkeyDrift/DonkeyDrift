# -*- coding: utf-8 -*-
"""鱼眼主摄像头内参标定（棋盘格流程，等距模型）—— 网页预览版。

与 calibrate_fisheye_camera.py 逻辑一致，但用浏览器代替 OpenCV 窗口：
实时画面通过 MJPEG 推送，网页按钮完成采集与求解，无需 GUI 构建。

用法：
    python scripts/calibrate_fisheye_web.py --camera 0 --width 320 --height 240 \
        --square 0.1 --out mycar/fisheye_intrinsics.npz [--port 8080]
然后浏览器打开 http://<本机IP>:8080/
"""
import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np

from calibrate_fisheye_camera import (CHECKERBOARD_FLAGS, FISHEYE_FLAGS,
                                      open_camera)

PAGE = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8"><title>鱼眼棋盘格标定</title>
<style>
body{font-family:sans-serif;background:#222;color:#eee;text-align:center}
img{max-width:96vw;image-rendering:auto;border:1px solid #555}
button{font-size:18px;margin:8px;padding:10px 24px;cursor:pointer}
#status{font-size:18px;margin:8px;white-space:pre-line}
</style></head><body>
<h2>鱼眼棋盘格标定（格距 %(square).3f m，%(cols)d×%(rows)d 内角点）</h2>
<img src="/stream" alt="camera stream">
<div>
<button onclick="fetch('/capture',{method:'POST'}).then(r=>r.json()).then(s=>flash(s.msg))">采集（空格）</button>
<button onclick="fetch('/auto',{method:'POST'}).then(r=>r.json()).then(s=>flash(s.msg))">自动采集开/关</button>
<button onclick="if(confirm('结束并求解？'))fetch('/finish',{method:'POST'}).then(r=>r.json()).then(s=>flash(s.msg))">结束并求解（ESC）</button>
</div>
<div id="status">加载中…</div>
<script>
function flash(m){document.getElementById('status').textContent=m}
setInterval(()=>fetch('/status').then(r=>r.json()).then(s=>{
  flash(`已采集 ${s.count} 张（目标 ≥${s.min_images}）\\n`+
        (s.found?'✅ 已识别棋盘格':'⚠️ 未识别棋盘格')+(s.result?'\\n'+s.result:''))
}),500);
</script></body></html>
"""


class Calibrator:
    def __init__(self, args):
        self.args = args
        self.cap = open_camera(args.camera, args.width, args.height, args.fps)
        if not self.cap.isOpened():
            raise RuntimeError(f"无法打开相机 index={args.camera}")
        self.objp = np.zeros((1, args.rows * args.cols, 3), np.float64)
        self.objp[0, :, :2] = (np.mgrid[0:args.cols, 0:args.rows].T
                               .reshape(-1, 2) * args.square)
        self.obj_points, self.img_points = [], []
        self.image_size = (0, 0)
        self.lock = threading.Lock()
        self.jpeg = None
        self.found = False
        self.corners = None
        self.pattern = None
        self.result = ""
        self.running = True
        self.auto = False
        self.last_auto = 0.0

    def detect(self, gray):
        """检测棋盘格角点。

        强鱼眼畸变下整块板常无法识别，依次尝试：
        1. 完整板（普通检测器 -> SB 检测器）
        2. 逐步缩小的子网格（标定时每视图有独立外参，
           子网格用局部坐标完全等价，格距不变即可）
        返回 (pattern, corners)，未识别返回 (None, None)。
        """
        primary = (self.args.cols, self.args.rows)
        sizes = [primary]
        for area_cols in range(primary[0] - 1, 4, -1):
            for area_rows in range(primary[1], 3, -1):
                sizes.append((area_cols, area_rows))
        sizes.append((primary[0], primary[1] - 1))
        for pattern in sizes:
            if pattern[0] < 4 or pattern[1] < 4:
                continue
            found, corners = cv2.findChessboardCorners(
                gray, pattern, CHECKERBOARD_FLAGS)
            if not found:
                try:
                    found, corners = cv2.findChessboardCornersSB(
                        gray, pattern,
                        flags=cv2.CALIB_CB_EXHAUSTIVE | cv2.CALIB_CB_ACCURACY)
                except cv2.error:
                    found = False
            if found:
                criteria = (cv2.TERM_CRITERIA_EPS
                            + cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-4)
                refined = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1),
                                           criteria)
                # 单应性 sanity check：剔除“之”字形等假网格。
                # 鱼眼下平面网格不严格满足单应，阈值放宽到 4px 只挡假阳性。
                obj_xy = (np.mgrid[0:pattern[0], 0:pattern[1]].T
                          .reshape(-1, 2).astype(np.float64))
                H, _ = cv2.findHomography(obj_xy,
                                          refined.reshape(-1, 2))
                if H is None:
                    continue
                proj = cv2.perspectiveTransform(
                    obj_xy.reshape(1, -1, 2), H).reshape(-1, 2)
                err = np.mean(np.linalg.norm(
                    proj - refined.reshape(-1, 2), axis=1))
                if err > 4.0:
                    continue
                return pattern, refined
        return None, None

    def loop(self):
        while self.running:
            ok, frame = self.cap.read()
            if not ok:
                time.sleep(0.01)
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            self.image_size = gray.shape[::-1]
            pattern, refined = self.detect(gray)
            found = pattern is not None
            display = frame.copy()
            if found:
                cv2.drawChessboardCorners(display, pattern, refined, found)
            label = (f"captured: {len(self.img_points)}"
                     + (f"  grid {pattern[0]}x{pattern[1]}" if found
                        else "  no board"))
            cv2.putText(display, label, (10, 25), cv2.FONT_HERSHEY_SIMPLEX,
                        0.6, (0, 255, 0) if found else (0, 0, 255), 2)
            ok, buf = cv2.imencode(".jpg", display,
                                   [cv2.IMWRITE_JPEG_QUALITY, 85])
            with self.lock:
                self.jpeg = buf.tobytes() if ok else None
                self.found = found
                self.corners = refined
                self.pattern = pattern
                self.frame = frame
            if self.auto and found:
                now = time.time()
                if now - self.last_auto > 1.5:
                    with self.lock:
                        moved = True
                        if self.img_points:
                            last = self.img_points[-1].reshape(-1, 2)
                            cur = self.corners.reshape(-1, 2)
                            if (last.shape == cur.shape
                                    and np.mean(np.abs(last - cur)) < 3):
                                moved = False
                        if moved:
                            self._store_view()
                            self.last_auto = now

    def _store_view(self):
        """存储当前识别到的视角（调用方须持有 self.lock）。"""
        cols, rows = self.pattern
        objp = np.zeros((1, cols * rows, 3), np.float64)
        objp[0, :, :2] = (np.mgrid[0:cols, 0:rows].T
                          .reshape(-1, 2) * self.args.square)
        self.obj_points.append(objp)
        self.img_points.append(
            self.corners.reshape(1, -1, 2).astype(np.float64))
        idx = len(self.img_points) - 1
        # 保存原始帧供离线核查
        frames_dir = Path(self.args.out).parent / "calib_frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(frames_dir / f"view_{idx:03d}.jpg"), self.frame)
        # 每视角实时存盘点，防止进程退出丢失
        points_path = str(Path(self.args.out).with_suffix("")) + ".points.npz"
        data = {"image_size": np.array(self.image_size)}
        for i in range(len(self.img_points)):
            data[f"obj_{i}"] = self.obj_points[i]
            data[f"img_{i}"] = self.img_points[i]
        np.savez(points_path, **data)
        return f"✅ 已采集 {len(self.img_points)} 张（{cols}×{rows} 网格）"

    def capture(self):
        with self.lock:
            if not self.found or self.corners is None:
                return "⚠️ 未识别棋盘格，本次未采集"
            return self._store_view()

    def _solve(self, idxs):
        K = np.eye(3, dtype=np.float64)
        D = np.zeros((4, 1), dtype=np.float64)
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
                    30, 1e-4)
        return cv2.fisheye.calibrate(
            [self.obj_points[i] for i in idxs],
            [self.img_points[i] for i in idxs],
            self.image_size, K, D, flags=FISHEYE_FLAGS, criteria=criteria)

    def finish(self):
        n = len(self.img_points)
        if n < self.args.min_images:
            return f"采集不足（{n}/{self.args.min_images}），请继续采集"
        # 求解前先存盘，失败也不丢数据
        data = {}
        for i in range(n):
            data[f"obj_{i}"] = self.obj_points[i]
            data[f"img_{i}"] = self.img_points[i]
        points_path = str(Path(self.args.out).with_suffix("")) + ".points.npz"
        np.savez(points_path, image_size=np.array(self.image_size), **data)
        dropped = []
        try:
            rms, K, D, _, _ = self._solve(list(range(n)))
        except cv2.error:
            # 逐个剔除问题视角重试
            rms = None
            for i in range(n):
                idxs = [j for j in range(n) if j != i]
                if len(idxs) < self.args.min_images - 3:
                    break
                try:
                    rms, K, D, _, _ = self._solve(idxs)
                    dropped = [i]
                    break
                except cv2.error:
                    continue
            if rms is None:
                return (f"求解失败：存在退化视角且单点剔除无法修复。\n"
                        f"采集点已保存：{points_path}，可离线分析")
        np.savez(self.args.out, camera_matrix=K, dist_coeffs=D,
                 image_size=np.array(self.image_size), rms=rms)
        self.result = (f"RMS = {rms:.3f}px（<0.5 为佳）\n"
                       + (f"已剔除问题视角：{dropped}\n" if dropped else "")
                       + f"已保存：{Path(self.args.out).resolve()}")
        return self.result


def make_handler(cal):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, msg):
            body = json.dumps({"msg": msg}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/":
                body = (PAGE % {"square": cal.args.square,
                                "cols": cal.args.cols,
                                "rows": cal.args.rows}).encode()
                self.send_response(200)
                self.send_header("Content-Type",
                                 "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/stream":
                self.send_response(200)
                self.send_header("Content-Type",
                                 "multipart/x-mixed-replace; boundary=frame")
                self.end_headers()
                try:
                    while True:
                        with cal.lock:
                            jpeg = cal.jpeg
                        if jpeg:
                            self.wfile.write(b"--frame\r\nContent-Type: "
                                             b"image/jpeg\r\n\r\n" + jpeg
                                             + b"\r\n")
                        time.sleep(0.05)
                except (BrokenPipeError, ConnectionResetError):
                    pass
            elif self.path == "/status":
                body = json.dumps({
                    "count": len(cal.img_points),
                    "min_images": cal.args.min_images,
                    "found": cal.found,
                    "result": cal.result,
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            if self.path == "/capture":
                self._json(cal.capture())
            elif self.path == "/finish":
                self._json(cal.finish())
            elif self.path == "/auto":
                cal.auto = not cal.auto
                self._json("自动采集已" + ("开启" if cal.auto else "关闭"))
            else:
                self.send_response(404)
                self.end_headers()

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description="鱼眼棋盘格标定（网页预览版）")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--width", type=int, default=320)
    parser.add_argument("--height", type=int, default=240)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--square", type=float, default=0.025, help="格距（米）")
    parser.add_argument("--cols", type=int, default=9)
    parser.add_argument("--rows", type=int, default=6)
    parser.add_argument("--min-images", type=int, default=15)
    parser.add_argument("--out", default="fisheye_intrinsics.npz")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    cal = Calibrator(args)
    threading.Thread(target=cal.loop, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", args.port), make_handler(cal))
    print(f"浏览器打开 http://localhost:{args.port}/ 进行标定"
          f"（格距 {args.square} m，目标 ≥{args.min_images} 张）", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        cal.running = False
        cal.cap.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
