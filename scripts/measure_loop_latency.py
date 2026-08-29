# -*- coding: utf-8 -*-
"""端到端延迟分段实测（M0 第一验收项，RFC 第 10 节）。

三段分别测量并汇总：
1. 视觉段：相机读帧 + AprilTag 检测耗时（俯拍相机 + 车顶标签）
2. 通路段：ws 控制下发 → 车端回显往返（需车端在线；用 drive ws 的
   request_car_state 请求-响应近似往返时延）
3. 处理段：β 估计 + 控制器 update 耗时（合成数据基准）

判定：三段 P95 合计预算 ~100ms，超标按 RFC 加超前补偿再评估。

用法：
    python scripts/measure_loop_latency.py --camera 0 [--seconds 10]
    python scripts/measure_loop_latency.py --server ws://<SBC或本机>:8000 [--seconds 10]
"""
import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path


def percentile95(samples_ms):
    if not samples_ms:
        return float("nan")
    ordered = sorted(samples_ms)
    idx = min(int(len(ordered) * 0.95), len(ordered) - 1)
    return ordered[idx]


def measure_vision(camera_index: int, seconds: float, tag_id: int):
    """视觉段：读帧+检测耗时分布。"""
    import cv2
    from pupil_apriltags import Detector

    cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    cap.set(cv2.CAP_PROP_FPS, 60)
    if not cap.isOpened():
        raise RuntimeError(f"无法打开相机 index={camera_index}")
    detector = Detector(families="tag36h11")

    read_ms, detect_ms = [], []
    t_end = time.monotonic() + seconds
    detected = 0
    while time.monotonic() < t_end:
        t0 = time.perf_counter()
        ok, frame = cap.read()
        t1 = time.perf_counter()
        if not ok:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        dets = detector.detect(gray)
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


async def measure_ws_roundtrip(server: str, seconds: float):
    """通路段：ws 发送 request_car_state → 收到车端任意回包的往返分布。"""
    import websockets

    uri = f"{server}/api/drive/ws?role=client&client_id=latency-probe"
    rtts = []
    async with websockets.connect(uri) as ws:
        # 等初始状态推送过去
        await asyncio.sleep(0.5)
        t_end = time.monotonic() + seconds
        while time.monotonic() < t_end:
            await ws.send(json.dumps({"type": "request_car_state"}))
            t0 = time.perf_counter()
            try:
                await asyncio.wait_for(ws.recv(), timeout=1.0)
                rtts.append((time.perf_counter() - t0) * 1000)
            except asyncio.TimeoutError:
                pass
            await asyncio.sleep(0.05)
    return {"ws_roundtrip": {"samples": len(rtts),
                             "p95_ms": round(percentile95(rtts), 2),
                             "median_ms": round(statistics.median(rtts), 2) if rtts else None}}


def measure_control_path(seconds: float):
    """处理段：β 估计 + 控制器单帧耗时（合成数据）。"""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web_ui" / "backend"))
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
        results.update(measure_vision(args.camera, args.seconds, args.tag_id))
        print(json.dumps(results, ensure_ascii=False, indent=2))
    if args.server:
        print("测量 ws 通路往返…")
        results.update(await measure_ws_roundtrip(args.server, args.seconds))
        print(json.dumps(results, ensure_ascii=False, indent=2))
    print("测量控制处理段…")
    results.update(measure_control_path(args.seconds))

    print("\n===== 汇总 =====")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    vision_p95 = results.get("vision", {}).get("read_p95_ms", 0) + \
        results.get("vision", {}).get("detect_p95_ms", 0)
    ws_p95 = results.get("ws_roundtrip", {}).get("p95_ms", 0)
    ctrl_p95 = results.get("control_path", {}).get("p95_ms", 0)
    total = vision_p95 + ws_p95 / 2 + ctrl_p95  # ws 往返取单程近似
    print(f"端到端 P95 估计 ≈ {total:.1f}ms（预算 ~100ms）")
    print("✅ 预算内" if total < 100 else "❌ 超预算：按 RFC 第 10 节加超前补偿或降档评估")
    out = Path("latency_report.json")
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告已写入 {out.resolve()}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="端到端延迟分段实测")
    parser.add_argument("--camera", type=int, default=None, help="俯拍相机 index（测视觉段）")
    parser.add_argument("--tag-id", type=int, default=0)
    parser.add_argument("--server", default=None, help="drive 服务 ws://host:port（测通路段）")
    parser.add_argument("--seconds", type=float, default=10.0)
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
