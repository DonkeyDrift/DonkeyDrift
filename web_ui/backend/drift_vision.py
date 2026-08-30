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
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Optional, Protocol, Tuple

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


def draw_tag_overlay(frame: np.ndarray, homography: "FieldHomography",
                     corners: np.ndarray, pose: "Pose",
                     course_deg: Optional[float] = None) -> np.ndarray:
    """在预览帧上叠加识别结果：标签四角绿框 + 车头方向红箭头。

    箭头按含贴标补偿的 heading（场地系）从标签中心前伸 15cm，
    经单应性投回图像坐标绘制。course_deg（航迹角=速度方向，β=车头-航迹
    的视觉呈现）给定时先画深蓝色细箭、红箭压底——两箭对齐（β≈0）时
    只见红箭，漂移时张开夹角即 β。
    """
    import cv2
    pts = np.array(corners, dtype=np.int32).reshape(-1, 2)
    cv2.polylines(frame, [pts], True, (0, 255, 0), 4)
    x0, y0 = homography.field_to_image(pose.x, pose.y)
    if course_deg is not None:
        cdx = 0.15 * math.cos(math.radians(course_deg))
        cdy = 0.15 * math.sin(math.radians(course_deg))
        cx1, cy1 = homography.field_to_image(pose.x + cdx, pose.y + cdy)
        cv2.arrowedLine(frame, (int(x0), int(y0)), (int(cx1), int(cy1)),
                        (139, 0, 0), 3, tipLength=0.25)  # 深蓝
    dx = 0.15 * math.cos(math.radians(pose.heading_deg))
    dy = 0.15 * math.sin(math.radians(pose.heading_deg))
    x1, y1 = homography.field_to_image(pose.x + dx, pose.y + dy)
    cv2.arrowedLine(frame, (int(x0), int(y0)), (int(x1), int(y1)),
                    (0, 0, 255), 5, tipLength=0.25)
    return frame


# ── 小车中心轨迹（2s 滑窗，按速度绿→黄→红着色）────────────
class TrajectoryTrail:
    """小车中心轨迹滑窗：只保留最近 window_s 秒的点（场地坐标，米）。

    小车不动时新点持续落在同一位置——轨迹视觉上始终是一个点；
    超过窗口的旧点在 snapshot 时修剪（动态消失）。
    """

    def __init__(self, window_s: float = 2.0):
        self._window_s = window_s
        self._points: Deque[Tuple[float, float, float]] = deque()

    def add(self, t_s: float, x: float, y: float) -> None:
        self._points.append((t_s, x, y))

    def snapshot(self, now_s: float) -> List[Tuple[float, float, float]]:
        """修剪过期点并返回当前窗口内的 [(t_s, x, y), ...]。"""
        while self._points and now_s - self._points[0][0] > self._window_s:
            self._points.popleft()
        return list(self._points)


def _baseline_index(points: List[Tuple[float, float, float]], i: int,
                    baseline_s: float) -> int:
    """点 i 的差分基线下标：最近的满足跨度 ≥baseline_s 的前序点，无则取 0。"""
    for k in range(i - 1, -1, -1):
        if points[i][0] - points[k][0] >= baseline_s:
            return k
    return 0


def trail_speeds(points: List[Tuple[float, float, float]],
                 baseline_s: float = 0.2) -> List[float]:
    """逐点线速度（m/s）：以 baseline_s 前的点为差分基线抑制位姿噪声。

    窗口早期无满基线点时回退到最早点（跨度 <0.05s 记 0，防除零噪声）；
    首点恒为 0。
    """
    speeds: List[float] = []
    for i, (t, x, y) in enumerate(points):
        j = _baseline_index(points, i, baseline_s)
        dt = t - points[j][0]
        if i == 0 or dt < 0.05:
            speeds.append(0.0)
        else:
            speeds.append(math.hypot(x - points[j][1], y - points[j][2]) / dt)
    return speeds


def trail_course_deg(points: List[Tuple[float, float, float]],
                     baseline_s: float = 0.2,
                     min_step_m: float = 0.02) -> Optional[float]:
    """轨迹切线方向（航迹角）：末点与 baseline_s 前点的割线方向，(-180,180]。

    用于绘制 β 航迹箭头。不用 BetaEstimator 的逐帧差分 course_deg：低速时
    逐帧位移卡在 2cm 阈值附近，超阈帧对被位姿噪声主导，方向随机（实车
    现象：箭头垂直于真实运动方向）；0.2s 割线基线把噪声摊薄一个量级，
    且与屏幕上轨迹线天然相切。位移不足 min_step_m（静止/噪声级）或
    点不足时返回 None——调用方不画箭头。
    """
    if len(points) < 2:
        return None
    i = len(points) - 1
    j = _baseline_index(points, i, baseline_s)
    t0, x0, y0 = points[j]
    t1, x1, y1 = points[i]
    dx, dy = x1 - x0, y1 - y0
    if t1 - t0 < 0.05 or math.hypot(dx, dy) < min_step_m:
        return None
    return math.degrees(math.atan2(dy, dx))


def speed_to_bgr(speed_mps: float, max_mps: float = 2.0) -> Tuple[int, int, int]:
    """速度→颜色（BGR）：0=绿，max/2=黄，≥max=红，区间线性插值。"""
    t = min(max(speed_mps / max_mps, 0.0), 1.0)
    if t <= 0.5:
        return (0, 255, int(round(510.0 * t)))
    return (0, int(round(510.0 * (1.0 - t))), 255)


def draw_trajectory(frame: np.ndarray, homography: "FieldHomography",
                    points: List[Tuple[float, float, float]],
                    speeds: List[float], max_mps: float = 2.0) -> np.ndarray:
    """轨迹叠加：逐段按速度着色画线（绿→黄→红），最新点画实心圆点。

    检测丢失的帧也可单独调用（无绿框/箭头时轨迹不闪断）。
    """
    import cv2
    if not points:
        return frame
    px = [homography.field_to_image(x, y) for _, x, y in points]
    for i in range(1, len(points)):
        color = speed_to_bgr(speeds[i] if i < len(speeds) else 0.0, max_mps)
        cv2.line(frame, (int(px[i - 1][0]), int(px[i - 1][1])),
                 (int(px[i][0]), int(px[i][1])), color, 3)
    tail_speed = speeds[-1] if speeds else 0.0
    cv2.circle(frame, (int(px[-1][0]), int(px[-1][1])), 5,
               speed_to_bgr(tail_speed, max_mps), -1)
    return frame


class PoseSolver:
    """滑动窗中值 + 跳变拒绝的位姿平滑器（防单帧误检跳变）。

    新位姿与当前窗中值的距离超过 max_jump_m 时拒绝该帧（返回窗中值），
    防止标签瞬时误检把控制器输入打飞；窗未填满时原样通过。
    检测缺口（运动模糊）后的真实位移会被误判为连续离群：连续 window 帧
    一致被拒即采信当前位姿并重置窗——否则位姿会永久冻结在缺口前位置。
    """

    def __init__(self, homography: FieldHomography, window: int = 5,
                 max_jump_m: float = 0.5):
        self._homography = homography
        self._window = window
        self._max_jump_m = max_jump_m
        self._history: List[Pose] = []
        self._reject_streak = 0  # 连续被拒帧数（识别"真实位移" vs "单帧误检"）

    def push(self, pose: Pose) -> Pose:
        if len(self._history) < self._window:
            self._history.append(pose)
            self._reject_streak = 0
            return pose
        xs = np.median([p.x for p in self._history])
        ys = np.median([p.y for p in self._history])
        if math.hypot(pose.x - xs, pose.y - ys) > self._max_jump_m:
            self._reject_streak += 1
            if self._reject_streak >= self._window:
                self._history = [pose]
                self._reject_streak = 0
                return pose
            return Pose(x=float(xs), y=float(ys),
                        heading_deg=self._circular_median_heading(), t_s=pose.t_s)
        self._reject_streak = 0
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

    exposure：手动曝光，DirectShow 语义为 log2(秒)（-6=1/64s、-7=1/128s、
    -8=1/256s），None 保持自动。运动模糊是快推丢检测的根因：60fps 下自动
    曝光最长 16ms，1m/s 推移即把 78px 标签拖出 20%~40% 涂抹，必须把曝光
    压短；设值前必须先关自动曝光（DSHOW 约定 0.25=手动），否则被忽略。
    """

    def __init__(self, index: int = 0, width: int = 1280, height: int = 720,
                 fps: int = 60, exposure: Optional[float] = None):
        import cv2
        self._cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        self._cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self._cap.set(cv2.CAP_PROP_FPS, fps)
        if exposure is not None:
            self._cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)  # 手动
            self._cap.set(cv2.CAP_PROP_EXPOSURE, float(exposure))
        if not self._cap.isOpened():
            raise RuntimeError(f"无法打开相机 index={index}")

    def read(self) -> Tuple[np.ndarray, float]:
        ok, frame = self._cap.read()
        if not ok:
            raise RuntimeError("相机读帧失败")
        return frame, time.monotonic()

    def close(self) -> None:
        self._cap.release()


class FrameSource:
    """读帧/处理分离：后台线程持续取帧只留最新，处理循环不被采集阻塞。

    消费者 latest() 返回 (frame, t_s, seq)；seq 是帧序号，消费者可据此
    跳过重复帧（处理比采集快时不重复处理同一帧）。
    """

    def __init__(self, camera):
        self._camera = camera
        self._lock = threading.Lock()
        self._latest: Optional[Tuple[np.ndarray, float, int]] = None
        self._seq = 0
        self._running = False
        self.alive = False          # 泵线程存活标志（死亡供消费者触发看门狗）
        self.read_ema_ms = 0.0      # 相机读帧耗时指数滑动均值（诊断）
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._running = True
        self.alive = True
        self._thread = threading.Thread(target=self._pump, daemon=True,
                                        name="drift-frame-pump")
        self._thread.start()

    def _pump(self) -> None:
        import time as _time
        while self._running:
            try:
                t0 = _time.perf_counter()
                frame, t_s = self._camera.read()
                read_ms = (_time.perf_counter() - t0) * 1000.0
            except Exception:
                break
            self.read_ema_ms += 0.1 * (read_ms - self.read_ema_ms)
            with self._lock:
                self._seq += 1
                self._latest = (frame, t_s, self._seq)
        self.alive = False

    def latest(self) -> Optional[Tuple[np.ndarray, float, int]]:
        with self._lock:
            return self._latest

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None


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

    def __init__(self, families: str = "tag36h11", tag_size_m: float = 0.08,
                 downscale: int = 1, decode_sharpening: float = 0.6):
        if not _PUPIL_APRILTAGS_AVAILABLE:
            raise RuntimeError(
                "AprilTag 后端 pupil-apriltags 未安装：pip install pupil-apriltags "
                "（Windows 编译受阻时改用 WSL 或备选 pyapriltags，二进制 ABI 一致）")
        # decode_sharpening 取高于库默认 0.25：提升运动模糊标签的解码率
        self._det = _PupilDetector(families=families,
                                   decode_sharpening=decode_sharpening)
        self.tag_size_m = tag_size_m
        self.downscale = max(1, int(downscale))

    def detect(self, frame: np.ndarray) -> List[TagDetection]:
        import cv2
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if self.downscale <= 1:
            return self._detect_gray(gray, scale=1)
        small = cv2.resize(gray, (gray.shape[1] // self.downscale,
                                  gray.shape[0] // self.downscale),
                           interpolation=cv2.INTER_AREA)
        detections = self._detect_gray(small, scale=self.downscale)
        if detections:
            return detections
        # 半分辨率未检出→全分辨率重试：运动模糊下 360p 标签 ~39px 接近
        # AprilTag 检测下限，720p 余量翻倍。代价只落在难帧上（~30ms），
        # 好帧保持半分辨率 60fps 路径。
        return self._detect_gray(gray, scale=1)

    def _detect_gray(self, gray: np.ndarray, scale: int) -> List[TagDetection]:
        results = self._det.detect(gray)
        detections = []
        for r in results:
            corners = np.asarray(r.corners, dtype=np.float32)
            if scale > 1:
                corners = corners * scale
            detections.append(TagDetection(tag_id=r.tag_id, corners=corners))
        return detections


class FakeTagDetector:
    """合成检测器：直接返回预设检测（驱动位姿链路测试）。"""

    def __init__(self, detections: Optional[List[TagDetection]] = None):
        self._detections = detections or []

    def detect(self, frame: np.ndarray) -> List[TagDetection]:
        return list(self._detections)
