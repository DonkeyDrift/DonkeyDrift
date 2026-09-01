# -*- coding: utf-8 -*-
"""端到端延迟分段实测（M0 第一验收项，RFC 第 10 节）。

三段分别测量并汇总：
1. 视觉段：相机读帧 + AprilTag 检测耗时（俯拍相机 + 车顶标签，
   检测口径复用生产链路 web_ui/backend/drift_vision.AprilTagDetector）
2. 通路段：ws 控制下发 → 车端回显往返（需车端在线；用 drive ws 的
   request_car_state 请求-响应近似往返时延）
3. 处理段：β 估计 + 控制器 update 耗时（合成数据基准）

判定：三段 P95 合计预算 ~100ms，超标按 RFC 加超前补偿再评估。

用法：
    python scripts/measure_loop_latency.py --camera 0 [--exposure -7] [--seconds 10]
    python scripts/measure_loop_latency.py --server ws://<SBC或本机>:8000 [--seconds 10]
"""
import argparse
import asyncio
import json
import math
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web_ui" / "backend"))


def percentile95(samples_ms):
    if not samples_ms:
        return float("nan")
    ordered = sorted(samples_ms)
    idx = min(int(len(ordered) * 0.95), len(ordered) - 1)
    return ordered[idx]


def summarize_total_p95(results: dict):
    """端到端 P95 合计估计（ws 往返取单程近似）。

    已测量但无有效样本的段 p95 为 nan —— 整体无法判定，返回 None
    （nan < 100 为 False，直接比较会误报"超预算"）。
    """
    vision_p95 = results.get("vision", {}).get("read_p95_ms", 0) + \
        results.get("vision", {}).get("detect_p95_ms", 0)
    ws_p95 = results.get("ws_roundtrip", {}).get("p95_ms", 0)
    ctrl_p95 = results.get("control_path", {}).get("p95_ms", 0)
    if any(math.isnan(p) for p in (vision_p95, ws_p95, ctrl_p95)):
        return None
    return vision_p95 + ws_p95 / 2 + ctrl_p95


def measure_vision(camera_index: int, seconds: float, tag_id: int,
                   exposure=None):
    """视觉段：读帧+检测耗时分布。

    检测口径与生产链路 drift_vision 一致（AprilTagDetector downscale=2、
    decode_sharpening=0.6，BGR 帧输入，耗时含灰度化+半分辨率缩放）。
    exposure 为 DirectShow log2(秒) 手动曝光（-7=1/128s），设置前必须先
    关自动曝光（DSHOW 约定 0.25=手动，否则被忽略）——手动压短曝光抑制
    运动模糊是生产口径的一部分。
    """
    import cv2
    from drift_vision import AprilTagDetector

    cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    cap.set(cv2.CAP_PROP_FPS, 60)
    if exposure is not None:
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)  # 先关自动（DSHOW 0.25=手动）
        cap.set(cv2.CAP_PROP_EXPOSURE, float(exposure))
    if not cap.isOpened():
        raise RuntimeError(f"无法打开相机 index={camera_index}")
    detector = AprilTagDetector(downscale=2, decode_sharpening=0.6)

    read_ms, detect_ms = [], []
    t_end = time.monotonic() + seconds
    detected = 0
    while time.monotonic() < t_end:
        t0 = time.perf_counter()
        ok, frame = cap.read()
        t1 = time.perf_counter()
        if not ok:
            continue
        dets = detector.detect(frame)
        t2 = time.perf_counter()
        read_ms.append((t1 - t0) * 1000)
        detect_ms.append((t2 - t1) * 1000)
        if any(d.tag_id == tag_id for d in dets):
            detected += 1
    cap.release()
    frames = len(read_ms)
    return {
        "vision": {
            "frames": frames, "tag_hits": detected,
            "read_p95_ms": round(percentile95(read_ms), 2),
            "detect_p95_ms": round(percentile95(detect_ms), 2),
            "fps": round(frames / seconds, 1),
        }
    }


async def _drain_pending(ws, quiet_s: float = 0.3):
    """排空 ws 缓冲中已到达的消息，直到静默 quiet_s 秒。

    连接后服务端固定先推 car_connection + car_state 两条初始消息；请求
    超时后迟到的回包也会滞留缓冲。若不排空，这些消息会被下一次 recv
    瞬时消费，产生 ≈0ms 的假 RTT 样本。
    """
    while True:
        try:
            await asyncio.wait_for(ws.recv(), timeout=quiet_s)
        except asyncio.TimeoutError:
            return


async def measure_ws_roundtrip(server: str, seconds: float,
                               recv_timeout: float = 1.0,
                               interval_s: float = 0.05):
    """通路段：ws 发送 request_car_state → 收到车端任意回包的往返分布。"""
    import websockets

    uri = f"{server}/api/drive/ws?role=client&client_id=latency-probe"
    rtts = []
    async with websockets.connect(uri) as ws:
        await _drain_pending(ws)  # 先排空初始推送，再进测量循环
        t_end = time.monotonic() + seconds
        while time.monotonic() < t_end:
            await ws.send(json.dumps({"type": "request_car_state"}))
            t0 = time.perf_counter()
            try:
                await asyncio.wait_for(ws.recv(), timeout=recv_timeout)
                rtts.append((time.perf_counter() - t0) * 1000)
            except asyncio.TimeoutError:
                # 排空超时后迟到的回包，防止污染后续样本
                await _drain_pending(ws)
            await asyncio.sleep(interval_s)
    return {"ws_roundtrip": {"samples": len(rtts),
                             "p95_ms": round(percentile95(rtts), 2),
                             "min_ms": round(min(rtts), 2) if rtts else None,
                             "median_ms": round(statistics.median(rtts), 2) if rtts else None}}


def measure_control_path(seconds: float):
    """处理段：β 估计 + 控制器单帧耗时（合成数据）。"""
    from drift_controller import ControllerConfig, DriftController
    from state_estimator import BetaEstimator, PoseSample

    est = BetaEstimator()
    ctrl = DriftController(ControllerConfig())
    costs = []
    n = int(seconds * 60)
    for i in range(n):
        t = i / 60.0
        t0 = time.perf_counter()
        est.update(PoseSample(1.0, 1.0, 30.0, t), 100.0)
        ctrl.update(25.0, 100.0, (1.0, 1.0), t)
        costs.append((time.perf_counter() - t0) * 1000)
    return {"control_path": {"samples": n,
                             "p95_ms": round(percentile95(costs), 3),
                             "median_ms": round(statistics.median(costs), 3)}}


async def main_async(args) -> int:
    results = {}
    if args.camera is not None:
        print("测量视觉段（读帧+检测）…")
        results.update(measure_vision(args.camera, args.seconds, args.tag_id,
                                      exposure=args.exposure))
        print(json.dumps(results, ensure_ascii=False, indent=2))
    if args.server:
        print("测量 ws 通路往返…")
        results.update(await measure_ws_roundtrip(args.server, args.seconds))
        print(json.dumps(results, ensure_ascii=False, indent=2))
    print("测量控制处理段…")
    results.update(measure_control_path(args.seconds))

    print("\n===== 汇总 =====")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    # 先落盘报告再打印判定：即使终端输出异常，原始数据也不丢
    out = Path("latency_report.json")
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告已写入 {out.resolve()}")

    total = summarize_total_p95(results)
    if total is None:
        print("无有效样本：至少一段已测量但未取得有效数据，无法判定预算")
        return 1
    print(f"端到端 P95 估计 ≈ {total:.1f}ms（预算 ~100ms）")
    if total < 100:
        print("✅ 预算内")
        return 0
    print("❌ 超预算：按 RFC 第 10 节加超前补偿或降档评估")
    return 1


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):  # GBK 控制台防 ✅/❌ UnicodeEncodeError
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="端到端延迟分段实测")
    parser.add_argument("--camera", type=int, default=None, help="俯拍相机 index（测视觉段）")
    parser.add_argument("--tag-id", type=int, default=0)
    parser.add_argument("--exposure", type=float, default=None,
                        help="手动曝光（DSHOW log2 秒，如 -7=1/128s）；不设则保持自动")
    parser.add_argument("--server", default=None, help="drive 服务 ws://host:port（测通路段）")
    parser.add_argument("--seconds", type=float, default=10.0)
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
