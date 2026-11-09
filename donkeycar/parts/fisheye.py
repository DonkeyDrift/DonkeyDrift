# -*- coding: utf-8 -*-
"""鱼眼镜头去畸变图像变换（Part）。

把圆形鱼眼投影展平为直线（rectilinear / pinhole）投影，并自动去掉镜头
物理渐晕造成的四角/四边黑边、缩放到目标分辨率，从而得到一个"标准视野"。

标定优先：若提供棋盘格标定文件（含 camera_matrix / dist_coeffs），使用
等距（equidistant）鱼眼模型做精确去畸变；否则根据成像圆与假定 FOV 估算
一个等距模型作为回退（此时输出 FOV 为近似值，但"无黑边"仍由几何保证）。

本模块仅依赖 numpy 与 opencv。
"""
import logging
import os

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# 默认配置（均可在 myconfig.py 中覆盖）
DEFAULT_FOV_DEG = 160.0     # 回退模型的镜头圆形视场角（有标定文件时以标定为准）
DEFAULT_MAX_BLACK = 0.0     # 允许残留的黑边比例，0 表示四边完全无黑边


def estimate_image_circle(image, bright_frac=0.5, safety=0.98):
    """从一帧鱼眼图估计成像圆 (cx, cy, r)。

    成像圆之外是镜头物理渐晕造成的暗边。做法：
    1. 以有效亮区质心为圆心；
    2. 沿半径统计各环平均亮度 ring_mean(r)；
    3. 以内部亮区（半径 20%~60% 处）的平均亮度为基准，
       取 ring_mean 首次跌破 bright_frac×基准 且持续一段的半径作为成像圆边界；
    4. 乘安全系数 safety 略微内缩，避免映射到边缘的渐晕暗环。

    相对阈值对整体偏暗/偏亮的场景都稳健，比固定灰度阈值可靠。

    :param bright_frac: 边界判定阈值占内部亮度的比例，默认 0.5
    :param safety: 半径安全系数(<1 内缩)，默认 0.98
    """
    if image is None:
        raise ValueError("estimate_image_circle: image 为空")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    h, w = gray.shape[:2]
    g = gray.astype(np.float32)
    if (g > 25).sum() < 0.02 * g.size:
        raise ValueError("未能在图像中检测到有效成像区域（成像圆），可用 FISHEYE_CIRCLE 手工指定")
    ys, xs = np.nonzero(g > 25)
    cx, cy = float(xs.mean()), float(ys.mean())

    n_ang = 720
    angles = np.linspace(0.0, 2.0 * np.pi, n_ang, endpoint=False)
    max_r = int(np.ceil(np.hypot(max(cx, w - 1 - cx), max(cy, h - 1 - cy)))) + 2
    radii = np.arange(max_r)
    xi = np.clip(np.rint(cx + np.outer(np.cos(angles), radii)).astype(np.int32), 0, w - 1)
    yi = np.clip(np.rint(cy + np.outer(np.sin(angles), radii)).astype(np.int32), 0, h - 1)
    ring_mean = g[yi, xi].mean(axis=0)                  # (max_r,)

    # 内部亮区基准（避开中心高光与外围暗环）
    lo, hi = int(0.2 * max_r), int(0.6 * max_r)
    ref = float(np.median(ring_mean[lo:hi]))
    if ref <= 0:
        raise ValueError("未能估出有效成像圆半径，可用 FISHEYE_CIRCLE 手工指定")
    drop_thresh = bright_frac * ref

    # 从最亮处向外，找首次跌破阈值并持续 6 个采样点的半径
    start = int(np.argmax(ring_mean))
    below = ring_mean[start:] < drop_thresh
    win = 6
    radius = float(max_r)
    for i in range(len(below) - win + 1):
        if below[i:i + win].all():
            radius = float(start + i)
            break
    radius *= float(safety)
    if radius <= 0:
        raise ValueError("未能估出有效成像圆半径，可用 FISHEYE_CIRCLE 手工指定")
    return cx, cy, radius


class FisheyeUndistort:
    """鱼眼去畸变 + 去黑边 + 缩放（实时图像变换 Part）。

    配置项（myconfig.py，均可选）：
      FISHEYE_INTRINSICS          : 棋盘格标定文件(.npz)，含 camera_matrix / dist_coeffs /
                                    image_size；缺省或文件不存在时回退到估算模型
      FISHEYE_FOV_DEG             : 估算模型下的镜头圆形视场角(度)，默认 160
      FISHEYE_WIDTH/FISHEYE_HEIGHT: 输出分辨率；缺省则与输入相同
      FISHEYE_OUT_FOV_DEG         : 固定的输出水平视场角(度)；缺省则自动取"黑边 <= 阈值"下的最大视野
      FISHEYE_MAX_BLACK           : 允许残留的黑边比例(0~1)，默认 0（完全无黑边），调大可保留更多视野
      FISHEYE_CIRCLE              : (cx, cy, r) 成像圆手工覆盖值，缺省自动检测

    用法：在 myconfig.py 中使用 `TRANSFORMATIONS = ['FISHEYE']`
    """

    def __init__(self, config):
        self.intrinsics_path = getattr(config, "FISHEYE_INTRINSICS", None)
        self.fov_deg = float(getattr(config, "FISHEYE_FOV_DEG", DEFAULT_FOV_DEG) or DEFAULT_FOV_DEG)
        self.out_width = getattr(config, "FISHEYE_WIDTH", None)
        self.out_height = getattr(config, "FISHEYE_HEIGHT", None)
        self.out_fov_deg = getattr(config, "FISHEYE_OUT_FOV_DEG", None)
        self.max_black = max(0.0, float(getattr(config, "FISHEYE_MAX_BLACK", DEFAULT_MAX_BLACK)))
        circle = getattr(config, "FISHEYE_CIRCLE", None)
        self._fixed_circle = tuple(float(v) for v in circle) if circle else None

        self._K, self._D, self._calib_size = self._load_intrinsics()
        self._key = None
        self._map1 = None
        self._map2 = None
        self.out_fov = None      # 实际得到的输出水平 FOV（度），构建后可用

    def _load_intrinsics(self):
        path = self.intrinsics_path
        if not path:
            return None, None, None
        if not os.path.exists(path):
            logger.warning("FISHEYE_INTRINSICS 文件不存在: %s，回退到估算模型", path)
            return None, None, None
        with np.load(path) as data:
            names = set(data.files)
            key_k = "camera_matrix" if "camera_matrix" in names else ("K" if "K" in names else None)
            key_d = "dist_coeffs" if "dist_coeffs" in names else ("D" if "D" in names else None)
            if key_k is None or key_d is None:
                raise ValueError(f"标定文件缺少 camera_matrix/dist_coeffs: {path}")
            K = np.asarray(data[key_k], dtype=np.float64)
            D = np.asarray(data[key_d], dtype=np.float64).reshape(-1, 1)
            size = tuple(int(v) for v in data["image_size"]) if "image_size" in names else None
        logger.info("已加载鱼眼标定内参: %s", path)
        return K, D, size

    def _model(self, w, h, circle):
        """返回去畸变所需的 (K, D)。"""
        if self._K is not None:
            K = self._K.copy()
            if self._calib_size and tuple(self._calib_size) != (w, h):
                sx = w / float(self._calib_size[0])
                sy = h / float(self._calib_size[1])
                K[0, 0] *= sx
                K[1, 1] *= sy
                K[0, 2] *= sx
                K[1, 2] *= sy
                logger.warning("标定分辨率 %s 与输入 %sx%s 不一致，已按比例缩放内参",
                               self._calib_size, w, h)
            return K, self._D
        cx, cy, r = circle
        theta_max = np.deg2rad(min(self.fov_deg, 179.0) / 2.0)
        f = r / theta_max
        K = np.array([[f, 0.0, cx], [0.0, f, cy], [0.0, 0.0, 1.0]], dtype=np.float64)
        D = np.zeros((4, 1), dtype=np.float64)
        logger.info("使用估算鱼眼模型: f=%.1f, 圆形FOV=%.0f°, 圆心=(%.0f,%.0f), r=%.0f",
                    f, self.fov_deg, cx, cy, r)
        return K, D

    @staticmethod
    def _undistort_maps(K, D, focal, out_w, out_h):
        """以输出中心为主点、给定焦距，构造 输出像素 -> 源图像素 的映射。"""
        K_new = np.array([[focal, 0.0, out_w / 2.0],
                          [0.0, focal, out_h / 2.0],
                          [0.0, 0.0, 1.0]], dtype=np.float64)
        return cv2.fisheye.initUndistortRectifyMap(
            K, D, np.eye(3, dtype=np.float64), K_new, (out_w, out_h), cv2.CV_32FC1)

    @staticmethod
    def _invalid_ratio(m1, m2, circle, w, h):
        """输出帧中映射落空（黑边）的比例。"""
        cx, cy, r = circle
        finite = np.isfinite(m1) & np.isfinite(m2)
        inside = (m1 >= 0) & (m1 <= w - 1) & (m2 >= 0) & (m2 <= h - 1)
        within_circle = ((m1 - cx) ** 2 + (m2 - cy) ** 2) <= (r * r)
        invalid = ~(finite & inside & within_circle)
        return float(invalid.mean())

    def _resolve_focal(self, K, D, circle, w, h, out_w, out_h):
        """确定输出焦距：可选固定 FOV，或在黑边阈值内取最大视野。"""
        if self.out_fov_deg:
            focal = (out_w / 2.0) / np.tan(np.deg2rad(self.out_fov_deg) / 2.0)
            m1, m2 = self._undistort_maps(K, D, focal, out_w, out_h)
            ratio = self._invalid_ratio(m1, m2, circle, w, h)
            if ratio > self.max_black:
                logger.warning("指定 FISHEYE_OUT_FOV_DEG=%.0f° 会产生 %.1f%% 黑边（阈值 %.1f%%）",
                               self.out_fov_deg, ratio * 100, self.max_black * 100)
            return focal

        # 二分搜索：焦距越小视野越大但黑边越多，取黑边 <= 阈值下的最小焦距
        hi = 8.0 * max(out_w, out_h)   # 视野极窄，必然无黑边
        lo = 1.0                       # 视野极大，通常有黑边

        def black_at(f):
            m1, m2 = self._undistort_maps(K, D, f, out_w, out_h)
            return self._invalid_ratio(m1, m2, circle, w, h)

        if black_at(hi) > self.max_black:
            raise ValueError("无法在给定成像圆/标定下构造无黑边视野，请检查 FISHEYE_CIRCLE/FOV/标定文件")
        if black_at(lo) <= self.max_black:
            return lo
        for _ in range(24):
            mid = 0.5 * (lo + hi)
            if black_at(mid) <= self.max_black:
                hi = mid
            else:
                lo = mid
        return hi

    def _build(self, w, h, circle):
        K, D = self._model(w, h, circle)
        out_w = int(self.out_width) if self.out_width else w
        out_h = int(self.out_height) if self.out_height else h
        focal = self._resolve_focal(K, D, circle, w, h, out_w, out_h)
        m1, m2 = self._undistort_maps(K, D, focal, out_w, out_h)
        self.out_fov = 2.0 * np.degrees(np.arctan((out_w / 2.0) / focal))
        logger.info("鱼眼去畸变就绪: 输入 %sx%s -> 输出 %sx%s, 等效水平FOV≈%.0f°, 黑边≈%.2f%%",
                    w, h, out_w, out_h, self.out_fov,
                    100.0 * self._invalid_ratio(m1, m2, circle, w, h))
        return m1, m2

    def run(self, image):
        if image is None:
            return None
        h, w = image.shape[:2]
        key = (h, w)
        if key != self._key:
            circle = self._fixed_circle or estimate_image_circle(image)
            self._map1, self._map2 = self._build(w, h, circle)
            self._key = key
        return cv2.remap(image, self._map1, self._map2,
                         interpolation=cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))

    def shutdown(self):
        self._map1 = None
        self._map2 = None
        self._key = None
