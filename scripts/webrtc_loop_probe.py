#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WebRTC 视频链路闭环探针（Python 接收端）。

以"合成浏览器"身份完成信令握手，用 aiortc 接收车端推流并逐帧解码，
从像素中读出捕获时刻印章（车端 DRIVE_WEBRTC_LATENCY_PROBE=1 时烧入），
输出帧率与端到端时延实测报告——整条链路（相机→缓冲→编码→打包→
回环网络→解码→像素）无盲区。

端到端时延 = 探针解码出帧的时刻 − 帧印章捕获时刻，两端各自 NTP 式
同步到后端 /api/drive/time 统一时钟域。不含浏览器呈现/垂直同步段
（该段由前端 rVFC captureTime 通路另行实测，两者相加即完整 e2e）。

用法：
  python scripts/webrtc_loop_probe.py --backend http://127.0.0.1:8001 --duration 10
  # 门禁模式（闭环测试断言，不达标退出码 1）：
  python scripts/webrtc_loop_probe.py ... --gate-fps 59 --gate-latency-ms 30

注意：会创建新 WebRTC 会话，单客户端模式下将接管当前浏览器会话。
"""
import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path
from typing import List, Optional

import requests

# 直连 session：绕过 http_proxy/all_proxy env（同 drive_api_bridge）
_direct_session = requests.Session()
_direct_session.trust_env = False

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import av  # noqa: E402
import numpy as np  # noqa: E402
from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription  # noqa: E402
from aiortc.sdp import candidate_from_sdp  # noqa: E402

from donkeycar.parts.video_timestamp import read_timestamp  # noqa: E402

from aiortc.jitterbuffer import JitterBuffer as _JitterBuffer, JitterFrame as _JitterFrame  # noqa: E402
from aiortc import rtcrtpreceiver as _rtcrtpreceiver  # noqa: E402


class MarkerReleaseJitterBuffer(_JitterBuffer):
    """按 marker 位立即释放完整帧的抖动缓冲（修正探针测量口径）。

    aiortc 上游 JitterBuffer._remove_frame 靠「下一帧首包的时间戳变化」判界，
    每个已完整收齐的视频帧会被押到下一帧首包到达才交给解码——接收端固定
    多付一个帧周期（20fps 源 +50ms、60fps 源 +16.7ms），使本探针的时延
    测量系统性虚高（实测 20fps 真实流 p50 63ms，实际 15ms）。浏览器不走
    这段逻辑（Chrome jitterBufferTarget=0 立即出帧），故只修探针侧。
    车端 VP8 打包器（aiortc Vp8Encoder._packetize）在每个帧最后一个包置
    marker=1，这里据此立即出帧，与浏览器行为对齐。
    """

    def add(self, packet):
        pli, frame = super().add(packet)
        if frame is None and getattr(packet, "marker", 0):
            frame = self._release_through_marker()
        return pli, frame

    def _release_through_marker(self):
        packets = []
        remove = 0
        timestamp = None
        found = False
        for count in range(self._capacity):
            pos = (self._origin + count) % self._capacity
            pkt = self._packets[pos]
            if pkt is None:
                break
            if timestamp is None:
                timestamp = pkt.timestamp
            elif pkt.timestamp != timestamp:
                break
            packets.append(pkt)
            remove = count + 1
            if pkt.marker:
                found = True
                break
        if not found:
            return None
        frame = _JitterFrame(data=b"".join(p._data for p in packets), timestamp=timestamp)
        self.remove(remove)
        return frame


# 探针进程内替换：RTCRtpReceiver 构造 video 抖动缓冲时用 marker 释放版
_rtcrtpreceiver.JitterBuffer = MarkerReleaseJitterBuffer

try:
    import websockets
except ImportError:  # pragma: no cover
    websockets = None


def _ws_connect_kwargs():
    """探针连后端永远绕过代理 env，理由同 requests（见 run_probe）。"""
    if websockets is None:
        return {}
    import inspect
    try:
        if "proxy" in inspect.signature(websockets.connect).parameters:
            return {"proxy": None}
    except (TypeError, ValueError):
        pass
    return {}


WS_NO_PROXY_KWARGS = _ws_connect_kwargs()


def sync_clock_to_backend(backend: str, samples: int = 5) -> tuple:
    """返回 (offset_s, rtt_s)：后端时钟 − 本机时钟，取 RTT 最小样本。"""
    best = None
    for _ in range(samples):
        t0 = time.time()
        # trust_env=False：all_proxy env 会把回环请求发给代理机（实测 502）；
        # proxies={'http': None} 无效——requests merge_setting 删 None 键
        resp = _direct_session.get(f"{backend}/api/drive/time", timeout=3)
        t1 = time.time()
        rtt = t1 - t0
        offset = float(resp.json()["server_time"]) - (t0 + rtt / 2.0)
        if best is None or rtt < best[0]:
            best = (rtt, offset)
    return best[1], best[0]


def percentile(values: List[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(len(ordered) * ratio + 0.999999) - 1))
    return ordered[index]


async def run_probe(backend: str, duration: float, connect_timeout: float,
                    probe_offset_s: float = 0.0) -> dict:
    if websockets is None:
        raise RuntimeError("缺少 websockets 依赖")

    ws_base = backend.replace("http://", "ws://").replace("https://", "wss://")
    client_id = f"loop-probe-{int(time.time() * 1000)}"
    session = requests.Session()
    # 后端是本机/局域网地址：绕过 shell 代理 env（http_proxy 会把请求
    # 发给代理机，回环目标会被解析到代理机自身的回环）
    session.trust_env = False

    car_offset_ms = 0.0
    try:
        stats = session.get(f"{backend}/api/drive/webrtc/stats", timeout=3).json()
        car_offset_ms = float(stats.get("clock_offset_ms") or 0.0)
    except Exception:
        pass

    loop = asyncio.get_running_loop()
    frame_queue: asyncio.Queue = asyncio.Queue()
    remote_candidates: asyncio.Queue = asyncio.Queue()
    answer_future: asyncio.Future = loop.create_future()

    pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    track_holder = {}

    @pc.on("track")
    def on_track(track):
        track_holder["track"] = track

        async def pump():
            while True:
                try:
                    frame = await track.recv()
                except Exception:
                    break
                await frame_queue.put(frame)

        loop.create_task(pump())

    @pc.on("icecandidate")
    def on_icecandidate(_candidate):
        pass  # aiortc 无 trickle：候选已在 localDescription.sdp 里随 offer 发出

    session_id = session.post(
        f"{backend}/api/drive/webrtc/session",
        json={"client_id": client_id}, timeout=5,
    ).json()["session_id"]

    async with websockets.connect(
        f"{ws_base}/api/drive/ws?role=client&client_id={client_id}",
        open_timeout=connect_timeout, **WS_NO_PROXY_KWARGS,
    ) as ws:

        async def signal_reader():
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("type") != "webrtc_signal":
                    continue
                if msg.get("signal_type") == "answer" and not answer_future.done():
                    answer_future.set_result(msg)
                elif msg.get("signal_type") == "ice" and msg.get("candidate"):
                    await remote_candidates.put(msg["candidate"])

        reader_task = loop.create_task(signal_reader())

        pc.addTransceiver("video", direction="recvonly")
        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)
        session.post(
            f"{backend}/api/drive/webrtc/offer",
            json={"session_id": session_id, "sdp": pc.localDescription.sdp, "type": "offer"},
            timeout=5,
        )

        answer = await asyncio.wait_for(answer_future, timeout=connect_timeout)
        await pc.setRemoteDescription(
            RTCSessionDescription(sdp=answer["sdp"], type="answer"))

        async def drain_candidates():
            while True:
                candidate = await remote_candidates.get()
                parsed = candidate_from_sdp(candidate["candidate"].removeprefix("candidate:"))
                parsed.sdpMid = candidate.get("sdpMid")
                parsed.sdpMLineIndex = candidate.get("sdpMLineIndex")
                try:
                    await pc.addIceCandidate(parsed)
                except Exception:
                    pass

        drain_task = loop.create_task(drain_candidates())

        # 等待连接建立 + 首帧到达
        deadline = time.monotonic() + connect_timeout
        while pc.connectionState != "connected" and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        if pc.connectionState != "connected":
            raise RuntimeError(f"WebRTC 连接失败: {pc.connectionState}")

        connected_at = time.time()
        stamp_times: List[float] = []
        recv_times: List[float] = []
        all_recv_times: List[float] = []
        seen_stamps = set()
        repeats = 0
        decoded = 0
        no_stamp = 0
        checksum_ok_probe_start = time.time()

        sample_deadline = time.monotonic() + duration
        while time.monotonic() < sample_deadline:
            try:
                frame = await asyncio.wait_for(frame_queue.get(), timeout=2.0)
            except asyncio.TimeoutError:
                break
            arr = frame.to_ndarray(format="rgb24")
            decoded += 1
            # 接收时刻统一到后端时钟域：本机钟 + 探针 offset
            recv_at = time.time() + probe_offset_s
            all_recv_times.append(recv_at)
            stamp = read_timestamp(arr)
            if stamp is None:
                no_stamp += 1
                continue
            if stamp in seen_stamps:
                # 节拍重复帧（同印章，60Hz 补帧产物）：计入链路帧率 link_fps，
                # 不进时延/间隔样本——时延口径是「采集→首现」，重复帧内容
                # 早已首现计过，再计会把补帧间隔掺进真实时延。
                repeats += 1
                continue
            seen_stamps.add(stamp)
            stamp_times.append(stamp + car_offset_ms / 1000.0)
            recv_times.append(recv_at)

        drain_task.cancel()
        reader_task.cancel()

    await pc.close()

    total = len(recv_times)
    if total < 10:
        raise RuntimeError(
            f"采样帧数不足（{total}，无印章 {no_stamp}）——"
            "车端未开启 DRIVE_WEBRTC_LATENCY_PROBE=1 或链路断流")

    latencies = [(r - s) * 1000.0 for r, s in zip(recv_times, stamp_times)]
    intervals = [
        (stamp_times[i] - stamp_times[i - 1]) * 1000.0
        for i in range(1, len(stamp_times)) if stamp_times[i] > stamp_times[i - 1]
    ]
    wall = stamp_times[-1] - stamp_times[0]
    link_intervals = [
        (all_recv_times[i] - all_recv_times[i - 1]) * 1000.0
        for i in range(1, len(all_recv_times)) if all_recv_times[i] > all_recv_times[i - 1]
    ]
    report = {
        "backend": backend,
        "car_clock_offset_ms": car_offset_ms,
        "duration_s": round(wall, 3),
        "frames_decoded": decoded,
        "frames_without_stamp": no_stamp,
        # 印章去重帧率 = 真实新内容帧率（源速率，瓶颈如实暴露）；
        # link_fps = 含节拍重复帧的链路出帧率（60Hz 补帧后应≈声明 fps）。
        "stamp_fps": round(total / wall, 2) if wall > 0 else 0.0,
        "link_fps": round(decoded / wall, 2) if wall > 0 else 0.0,
        "repeat_frames": repeats,
        "e2e_ms": {
            "p50": round(percentile(latencies, 0.5), 2),
            "p95": round(percentile(latencies, 0.95), 2),
            "min": round(min(latencies), 2),
            "max": round(max(latencies), 2),
            "mean": round(statistics.fmean(latencies), 2),
        },
        "frame_interval_ms": {
            "p50": round(percentile(intervals, 0.5), 2),
            "p95": round(percentile(intervals, 0.95), 2),
            "max": round(max(intervals), 2) if intervals else 0.0,
        },
        # 链路出帧间隔（含补帧）：60Hz 节拍稳定性口径
        "link_interval_ms": {
            "p50": round(percentile(link_intervals, 0.5), 2),
            "p95": round(percentile(link_intervals, 0.95), 2),
            "max": round(max(link_intervals), 2) if link_intervals else 0.0,
        },
    }
    return report


async def main_async() -> int:
    parser = argparse.ArgumentParser(description="WebRTC 视频链路闭环探针")
    parser.add_argument("--backend", default="http://127.0.0.1:8001")
    parser.add_argument("--duration", type=float, default=10.0, help="采样时长（秒）")
    parser.add_argument("--connect-timeout", type=float, default=15.0)
    parser.add_argument("--gate-fps", type=float, default=None, help="门禁：印章去重帧率下限")
    parser.add_argument("--gate-link-fps", type=float, default=None,
                        help="门禁：链路出帧率下限（含节拍重复帧）")
    parser.add_argument("--gate-latency-ms", type=float, default=None, help="门禁：e2e p95 上限")
    parser.add_argument("--json", action="store_true", help="仅输出 JSON")
    args = parser.parse_args()

    probe_offset, probe_rtt = sync_clock_to_backend(args.backend)
    if not args.json:
        print(f"探针时钟同步：offset={probe_offset * 1000:.2f}ms rtt={probe_rtt * 1000:.2f}ms",
              file=sys.stderr)
    report = await run_probe(args.backend, args.duration, args.connect_timeout,
                             probe_offset_s=probe_offset)

    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))

    failed = False
    if args.gate_fps is not None and report["stamp_fps"] < args.gate_fps:
        print(f"门禁失败：帧率 {report['stamp_fps']} < {args.gate_fps}", file=sys.stderr)
        failed = True
    if args.gate_link_fps is not None and report["link_fps"] < args.gate_link_fps:
        print(f"门禁失败：链路帧率 {report['link_fps']} < {args.gate_link_fps}", file=sys.stderr)
        failed = True
    if args.gate_latency_ms is not None and report["e2e_ms"]["p95"] > args.gate_latency_ms:
        print(f"门禁失败：e2e p95 {report['e2e_ms']['p95']}ms > {args.gate_latency_ms}ms",
              file=sys.stderr)
        failed = True
    return 1 if failed else 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
