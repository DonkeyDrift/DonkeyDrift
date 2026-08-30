# -*- coding: utf-8 -*-
"""第三视角俯拍视觉模块（RFC docs/Rfc/overhead-drift-control.md 第 5 节）。

职责：相机帧获取（抽象）、AprilTag 检测（抽象 + pupil-apriltags 后端）、
图像→场地单应性映射、车顶标签位姿解算与离群值平滑。

坐标约定（全模块统一）：
- 场地坐标系：x 向东、y 向北，单位米，原点在场地西南角；
- 图像坐标系：像素，y 轴向下——y 翻转在标定点对（from_correspondences
  的输入）中体现，本模块不做隐式翻转；
- 标签四角约定 corners = [前左, 前右, 后右, 后左]（车体系），heading
  由前边（前左→前右）在场地系的方向解出，输出范围 (-180, 180]。

相机与检测器均为可注入抽象：今晚无硬件时用 FakeCamera/FakeTagDetector
驱动纯几何逻辑测试，明天实机联调只替换实现、不动几何代码。
"""
import math
import time
from dataclasses import dataclass
from typing import List, Optional, Protocol, Tuple

import numpy as np

try:  # AprilTag 检测后端（明天实机联调；缺失时构造函数显式报错）
    from pupil_apriltags import Detector as _PupilDetector
    _PUPIL_APRILTAGS_AVAILABLE = True
except ImportError:
    _PUPIL_APRILTAGS_AVAILABLE = False


# ── 单应性：图像 ↔ 场地（米） ─────────────────────────────
class FieldHomography:
    """四点单应性。图像上方对应场地北侧的 y 翻转由标定点对携带。"""

    def __init__(self, matrix: np.ndarray):
        self._h = matrix
        self._h_inv = np.linalg.inv(matrix)

    @classmethod
    def from_correspondences(cls, image_pts: np.ndarray, field_pts: np.ndarray) -> "FieldHomography":
        import cv2
        h, _ = cv2.findHomography(np.asarray(image_pts, dtype=np.float32),
                                  np.asarray(field_pts, dtype=np.float32))
        if h is None:
            raise ValueError("单应性求解失败：检查四对标定点是否退化（共线/重复）")
        return cls(h)

    @classmethod
    def from_file(cls, path: str) -> "FieldHomography":
        data = np.load(path)
        return cls(data["h"])

    def to_file(self, path: str) -> None:
        np.savez(path, h=self._h)

    def _map(self, matrix: np.ndarray, x: float, y: float) -> Tuple[float, float]:
        v = np.array([x, y, 1.0])
        w = matrix @ v
        return float(w[0] / w[2]), float(w[1] / w[2])

    def image_to_field(self, px: float, py: float) -> Tuple[float, float]:
        return self._map(self._h, px, py)

    def field_to_image(self, fx: float, fy: float) -> Tuple[float, float]:
        return self._map(self._h_inv, fx, fy)


# ── 位姿 ──────────────────────────────────────────────────
@dataclass
class Pose:
    x: float
    y: float
    heading_deg: float
    t_s: float


def solve_tag_pose(homography: FieldHomography, corners: np.ndarray,
                   t_s: float = 0.0,
                   heading_offset_deg: float = 0.0) -> Pose:
    """由标签四角（图像坐标）解出车位姿。

    位置 = 四角场地坐标均值；朝向 = 前边（corner[0]→corner[1]）在场地系
    的方向。对单应性的非线性在小标签（~8cm）尺度下引入的误差远小于
    1cm/1° 验收容差（测试 TestPoseSolving 覆盖）。

    heading_offset_deg：补偿标签贴上车顶时相对车头的整体旋转
    （贴反 180° 填 180，转 90° 填 ±90），叠加后按 ±180° 环回。
    """
    pts_field = np.array([homography.image_to_field(*c) for c in corners])
    cx = float(pts_field[:, 0].mean())
    cy = float(pts_field[:, 1].mean())
    front = pts_field[1] - pts_field[0]
    heading_deg = math.degrees(math.atan2(front[1], front[0]))
    heading_deg = (heading_deg + heading_offset_deg + 180.0) % 360.0 - 180.0
    return Pose(x=cx, y=cy, heading_deg=heading_deg, t_s=t_s)


class PoseSolver:
    """滑动窗中值 + 跳变拒绝的位姿平滑器（防单帧误检跳变）。

    新位姿与当前窗中值的距离超过 max_jump_m 时拒绝该帧（返回窗中值），
    防止标签瞬时误检把控制器输入打飞；窗未填满时原样通过。
    """

    def __init__(self, homography: FieldHomography, window: int = 5,
                 max_jump_m: float = 0.5):
        self._homography = homography
        self._window = window
        self._max_jump_m = max_jump_m
        self._history: List[Pose] = []

    def push(self, pose: Pose) -> Pose:
        if len(self._history) < self._window:
            self._history.append(pose)
            return pose
        xs = np.median([p.x for p in self._history])
        ys = np.median([p.y for p in self._history])
        if math.hypot(pose.x - xs, pose.y - ys) > self._max_jump_m:
            return Pose(x=float(xs), y=float(ys),
                        heading_deg=self._circular_median_heading(), t_s=pose.t_s)
        self._history.append(pose)
        self._history = self._history[-self._window:]
        return pose

    def _circular_median_heading(self) -> float:
        angles = [math.radians(p.heading_deg) for p in self._history]
        mean_sin = float(np.median([math.sin(a) for a in angles]))
        mean_cos = float(np.median([math.cos(a) for a in angles]))
        deg = math.degrees(math.atan2(mean_sin, mean_cos))
        return deg if deg > -180.0 else deg + 360.0


# ── 相机抽象 ──────────────────────────────────────────────
class CameraSource(Protocol):
    """相机源接口：read() 返回 (BGR 帧, 笔记本单调时戳)。"""

    def read(self) -> Tuple[np.ndarray, float]: ...


class USBCamera:
    """UVC 相机实现（OpenCV VideoCapture，MJPG，曝光/帧率可配）。

    硬件明天到位后实例化；曝光以 CAP_PROP_EXPOSURE 设置（-directshow
    后端下的行为明天实测，失败则改用 v4l2/显式属性名）。
    """

    def __init__(self, index: int = 0, width: int = 1280, height: int = 720,
                 fps: int = 60, exposure_us: Optional[int] = None):
        import cv2
        self._cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        self._cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self._cap.set(cv2.CAP_PROP_FPS, fps)
        if exposure_us is not None:
            self._cap.set(cv2.CAP_PROP_EXPOSURE, exposure_us)
        if not self._cap.isOpened():
            raise RuntimeError(f"无法打开相机 index={index}")

    def read(self) -> Tuple[np.ndarray, float]:
        ok, frame = self._cap.read()
        if not ok:
            raise RuntimeError("相机读帧失败")
        return frame, time.monotonic()

    def close(self) -> None:
        self._cap.release()


class FakeCamera:
    """合成相机：黑帧 + 严格单调时戳，驱动无硬件环境下的逻辑测试。"""

    def __init__(self, shape=(480, 640, 3)):
        self._shape = shape
        self._t = time.monotonic()

    def read(self) -> Tuple[np.ndarray, float]:
        self._t += 1.0 / 60.0
        return np.zeros(self._shape, dtype=np.uint8), self._t


# ── AprilTag 检测抽象 ─────────────────────────────────────
@dataclass
class TagDetection:
    tag_id: int
    corners: np.ndarray  # 图像坐标四角，[前左, 前右, 后右, 后左]


class TagDetector(Protocol):
    def detect(self, frame: np.ndarray) -> List[TagDetection]: ...


class AprilTagDetector:
    """pupil-apriltags 后端。后端不可用时显式报错——不静默降级。

    角序联调说明：pupil_apriltags 的 corners 顺序与车体系约定的对齐
    （必要时重排）在明天实机标定时用一次已知朝向验证完成。
    """

    def __init__(self, families: str = "tag36h11", tag_size_m: float = 0.08):
        if not _PUPIL_APRILTAGS_AVAILABLE:
            raise RuntimeError(
                "AprilTag 后端 pupil-apriltags 未安装：pip install pupil-apriltags "
                "（Windows 编译受阻时改用 WSL 或备选 pyapriltags，二进制 ABI 一致）")
        self._det = _PupilDetector(families=families)
        self.tag_size_m = tag_size_m

    def detect(self, frame: np.ndarray) -> List[TagDetection]:
        import cv2
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        results = self._det.detect(gray)
        return [TagDetection(tag_id=r.tag_id, corners=np.asarray(r.corners, dtype=np.float32))
                for r in results]


class FakeTagDetector:
    """合成检测器：直接返回预设检测（驱动位姿链路测试）。"""

    def __init__(self, detections: Optional[List[TagDetection]] = None):
        self._detections = detections or []

    def detect(self, frame: np.ndarray) -> List[TagDetection]:
        return list(self._detections)
