#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端图传闭环测试编排器。

一个命令跑通「隔离后端 → 合成图传源 → 回环探针门禁 →（可选）headless 真实
浏览器实测」，结果落历史 JSONL 供迭代对比——改一个图传参数（码率/分辨率/
编码器开关…），重跑同一场景，--compare-last 直接看指标增减，形成优化闭环。

场景（--scenarios，逗号分隔，默认前三个）：

  pipeline-320p60   合成源 320x240@60 —— 管线能力/回归门禁（真车相机路径口径）
  pipeline-480p60   合成源 640x480@60 —— 预览编码上限分辨率下的管线能力
  simcadence-320p20 合成源 320x240@20 —— 模拟器节拍仿真（模拟器源固定 20fps）
  simcadence-480p20 合成源 640x480@20 —— 模拟器节拍 + 预览上限分辨率
  live              不起合成源，直接探测 --backend 指向的在跑车端（真实链路）
                    （须配合 --backend http://127.0.0.1:8000 使用）

门禁默认值见 SCENARIOS；--gate-fps/--gate-latency-ms 可整体覆盖。

浏览器支路（--browser）：自动探测 Chrome/Chromium/Edge，headless 打开 Drive 页，
页面自身完成 WebRTC 接入 + 像素印章采样并 POST 回后端，编排器轮询
/api/drive/webrtc/stats 直至 e2e 样本足够，取真实浏览器口径的 e2e p50/p95。

用法：
  # 全场景闭环（独立后端，不干扰在跑实例）
  env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
      -u all_proxy -u ALL_PROXY .venv/bin/python scripts/e2e_video_test.py

  # A/B 某个图传参数后对比
  ... scripts/e2e_video_test.py --scenarios pipeline-320p60 \
      --set DRIVE_WEBRTC_VIDEO_BITRATE=750000 --compare-last

  # 探测真实模拟器链路（车端已在跑时）
  ... scripts/e2e_video_test.py --scenarios live --backend http://127.0.0.1:8000

退出码：任一门禁失败 → 1（可作 CI 门禁）。
"""
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HISTORY = Path.home() / ".donkeycar" / "video_pipeline_history.jsonl"

# 直连：绕过 shell 代理 env（回环目标会被代理机劫持，实测 502）
STRIP_PROXY = ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
               "all_proxy", "ALL_PROXY")

SCENARIOS = {
    "pipeline-320p60": {"fps": 60, "width": 320, "height": 240,
                        "gate_fps": 58, "gate_latency_ms": 50},
    "pipeline-480p60": {"fps": 60, "width": 640, "height": 480,
                        "gate_fps": 58, "gate_latency_ms": 50},
    "simcadence-320p20": {"fps": 20, "width": 320, "height": 240,
                          "gate_fps": 19, "gate_latency_ms": 50},
    "simcadence-480p20": {"fps": 20, "width": 640, "height": 480,
                          "gate_fps": 19, "gate_latency_ms": 50},
    "live": {"gate_fps": 19, "gate_latency_ms": 50},
}

CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    str(Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
)


def clean_env(extra=None):
    env = {k: v for k, v in os.environ.items() if k not in STRIP_PROXY}
    if extra:
        env.update(extra)
    return env


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http_get_json(url: str, timeout: float = 3.0):
    req = urllib.request.Request(url, headers={"User-Agent": "e2e-video-test"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def http_post_json(url: str, payload: dict, timeout: float = 5.0):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "e2e-video-test"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


class Proc:
    """可 terminate 的子进程，失败时能倒出日志尾部。"""

    def __init__(self, args, cwd=None, env=None, name=""):
        self.name = name
        self.args = args
        self.log = tempfile.NamedTemporaryFile(
            prefix=f"e2evid-{name}-", suffix=".log", delete=False)
        self.proc = subprocess.Popen(
            args, cwd=cwd, env=env, stdout=self.log, stderr=subprocess.STDOUT)

    def tail(self, n: int = 25) -> str:
        try:
            self.log.flush()
            with open(self.log.name, "rb") as f:
                lines = f.read().decode(errors="replace").splitlines()
            return "\n".join(lines[-n:])
        except OSError:
            return "<log unavailable>"

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stop()


def wait_backend_ready(backend: str, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    last_err = None
    while time.monotonic() < deadline:
        try:
            http_get_json(f"{backend}/api/drive/time", timeout=2)
            return
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_err = exc
            time.sleep(0.4)
    raise RuntimeError(f"后端未就绪 {backend}: {last_err!r}")


def wait_car_online(backend: str, timeout: float = 25.0) -> None:
    """轮询创建 WebRTC 会话作为「车端在线」探测（成功即弃用，由探针另建）。"""
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            http_post_json(f"{backend}/api/drive/webrtc/session",
                           {"client_id": "readiness-probe"}, timeout=3)
            return
        except urllib.error.HTTPError as exc:
            last = exc
            time.sleep(0.6)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
            time.sleep(0.6)
    raise RuntimeError(f"车端未上线: {last!r}")


def run_probe(repo_root: Path, backend: str, duration: float,
              gate_fps: float, gate_latency_ms: float) -> dict:
    out = subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "webrtc_loop_probe.py"),
         "--backend", backend, "--duration", str(duration),
         "--json"],
        cwd=repo_root, env=clean_env(), capture_output=True, text=True,
        timeout=duration + 90,
    )
    if out.returncode != 0:
        raise RuntimeError(f"探针失败（exit {out.returncode}）:\n{out.stdout[-800:]}\n{out.stderr[-1500:]}")
    return json.loads(out.stdout.strip().splitlines()[-1])


def find_chrome(explicit: str = None):
    if explicit:
        return explicit if Path(explicit).exists() else None
    for path in CHROME_CANDIDATES:
        if Path(path).exists():
            return path
    which = shutil.which("chrome") or shutil.which("chromium") or shutil.which("google-chrome")
    return which


def run_browser_leg(backend: str, chrome: str, duration: float,
                    min_samples: int = 60) -> dict:
    """headless 真实浏览器支路：页面自行接入 WebRTC 并上报 e2e 样本。"""
    user_data = tempfile.mkdtemp(prefix="e2evid-chrome-")
    args = [
        chrome,
        "--headless=new",
        "--no-first-run", "--no-default-browser-check",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--autoplay-policy=no-user-gesture-required",
        f"--user-data-dir={user_data}",
        "--window-size=1280,900",
        f"{backend}/#/drive",
    ]
    proc = subprocess.Popen(args, env=clean_env(),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + duration
        stats = {}
        while time.monotonic() < deadline:
            time.sleep(2.0)
            try:
                stats = http_get_json(f"{backend}/api/drive/webrtc/stats")
            except (urllib.error.URLError, TimeoutError, OSError):
                continue
            if stats.get("e2e_samples", 0) >= min_samples:
                break
        return {
            "e2e_latency_p50_ms": stats.get("e2e_latency_p50_ms"),
            "e2e_latency_p95_ms": stats.get("e2e_latency_p95_ms"),
            "e2e_samples": stats.get("e2e_samples", 0),
            "inbound_fps": stats.get("inbound_fps"),
            "browser_fps": stats.get("browser_fps"),
            "jitter_buffer_delay_ms": stats.get("jitter_buffer_delay_ms"),
            "frames_dropped": stats.get("frames_dropped"),
        }
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(user_data, ignore_errors=True)


def evaluate_gates(scenario: dict, cfg: dict, probe: dict, browser: dict,
                   gate_fps: float, gate_latency_ms: float) -> list:
    checks = []
    fps = probe.get("stamp_fps", 0.0)
    p95 = probe.get("e2e_ms", {}).get("p95")
    checks.append(("探针帧率 ≥ 门限", fps >= gate_fps,
                   f"{fps} vs ≥{gate_fps}"))
    checks.append(("探针 e2e p95 ≤ 门限", p95 is not None and p95 <= gate_latency_ms,
                   f"{p95}ms vs ≤{gate_latency_ms}ms"))
    no_stamp = probe.get("frames_without_stamp")
    checks.append(("印章覆盖 100%", no_stamp == 0, f"无印章帧 {no_stamp}"))
    if browser is not None:
        bs = browser.get("e2e_samples") or 0
        bp95 = browser.get("e2e_latency_p95_ms")
        checks.append(("浏览器 e2e 样本足够", bs >= 60, f"samples={bs}"))
        checks.append(("浏览器 e2e p95 ≤ 门限",
                       bp95 is not None and bp95 <= gate_latency_ms,
                       f"{bp95}ms vs ≤{gate_latency_ms}ms"))
    return checks


def load_history(path: Path):
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def print_compare(entries, scenario: str):
    prevs = [e for e in entries if e.get("scenario") == scenario]
    if len(prevs) < 2:
        print(f"  [对比] {scenario}: 历史样本不足，无法对比")
        return
    prev, cur = prevs[-2], prevs[-1]
    p_probe, c_probe = prev.get("probe", {}), cur.get("probe", {})
    print(f"  [对比] {scenario}（vs 上一次同场景）:")
    for label, p_val, c_val in (
        ("stamp_fps", p_probe.get("stamp_fps"), c_probe.get("stamp_fps")),
        ("e2e p50", (p_probe.get("e2e_ms") or {}).get("p50"),
         (c_probe.get("e2e_ms") or {}).get("p50")),
        ("e2e p95", (p_probe.get("e2e_ms") or {}).get("p95"),
         (c_probe.get("e2e_ms") or {}).get("p95")),
    ):
        if p_val is not None and c_val is not None:
            delta = c_val - p_val
            print(f"    {label:10s} {p_val} → {c_val}（{delta:+.2f}）")


def main() -> int:
    parser = argparse.ArgumentParser(description="端到端图传闭环测试编排器")
    parser.add_argument("--scenarios",
                        default="pipeline-320p60,pipeline-480p60,simcadence-320p20",
                        help="逗号分隔；可选 " + ",".join(SCENARIOS))
    parser.add_argument("--list-scenarios", action="store_true")
    parser.add_argument("--backend", default=None,
                        help="复用在跑后端（如 http://127.0.0.1:8000）；缺省自动起隔离后端")
    parser.add_argument("--duration", type=float, default=20.0, help="探针采样秒数/场景")
    parser.add_argument("--browser", action="store_true", help="加跑 headless 真实浏览器支路")
    parser.add_argument("--chrome", default=None, help="浏览器可执行文件路径（缺省自动探测）")
    parser.add_argument("--set", dest="overrides", action="append", default=[],
                        metavar="K=V", help="传给合成源进程的环境变量（A/B 图传参数），可重复")
    parser.add_argument("--gate-fps", type=float, default=None, help="覆盖所有场景帧率门限")
    parser.add_argument("--gate-latency-ms", type=float, default=None, help="覆盖所有场景时延门限")
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    parser.add_argument("--compare-last", action="store_true", help="与历史中同场景上一次结果对比")
    parser.add_argument("--keep-backend", action="store_true", help="调试：测试后保留隔离后端进程")
    parser.add_argument("--json", action="store_true", help="只输出 JSON 汇总")
    args = parser.parse_args()

    if args.list_scenarios:
        for name, cfg in SCENARIOS.items():
            print(f"{name}: {cfg}")
        return 0

    names = [n.strip() for n in args.scenarios.split(",") if n.strip()]
    for n in names:
        if n not in SCENARIOS:
            parser.error(f"未知场景 {n}；可选：{','.join(SCENARIOS)}")
    if "live" in names and not args.backend:
        parser.error("live 场景必须 --backend 指向在跑后端（其车端即被测对象）")

    overrides = {}
    for item in args.overrides:
        if "=" not in item:
            parser.error(f"--set 需要 K=V 形式: {item}")
        k, v = item.split("=", 1)
        overrides[k.strip()] = v.strip()

    repo_root = REPO_ROOT
    own_backend = None
    backend = args.backend
    try:
        if backend is None:
            port = free_port()
            backend = f"http://127.0.0.1:{port}"
            print(f"[编排] 启动隔离后端 {backend} …")
            own_backend = Proc(
                [sys.executable, "-m", "uvicorn", "main:app",
                 "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
                cwd=repo_root / "web_ui" / "backend",
                env=clean_env({"DRIVE_WEB_PORT": str(port)}),
                name="backend")
            wait_backend_ready(backend)
        else:
            backend = backend.rstrip("/")
            wait_backend_ready(backend)
            print(f"[编排] 复用在跑后端 {backend}")

        chrome = find_chrome(args.chrome) if args.browser else None
        if args.browser and chrome is None:
            print("[编排] 未找到 Chrome/Chromium，浏览器支路跳过"
                  "（--chrome 指定路径可强制）")
        run_stamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        results = []
        all_pass = True

        for name in names:
            cfg = dict(SCENARIOS[name])
            if args.gate_fps is not None:
                cfg["gate_fps"] = args.gate_fps
            if args.gate_latency_ms is not None:
                cfg["gate_latency_ms"] = args.gate_latency_ms

            source = None
            probe = None
            browser = None
            error = None
            try:
                if name != "live":
                    print(f"[{name}] 启动合成源 {cfg['width']}x{cfg['height']}@{cfg['fps']} …")
                    source = Proc(
                        [sys.executable, str(repo_root / "scripts" / "synthetic_car_video.py"),
                         "--server", f"{backend.replace('http', 'ws', 1)}/api/drive/ws",
                         "--fps", str(cfg["fps"]),
                         "--width", str(cfg["width"]),
                         "--height", str(cfg["height"]),
                         "--probe"],
                        cwd=repo_root, env=clean_env(overrides), name=f"src-{name}")
                    time.sleep(4.0)  # 等车端 WS 接入并开始推帧
                wait_car_online(backend)

                print(f"[{name}] 回环探针 {args.duration}s（门限 fps≥{cfg['gate_fps']} "
                      f"p95≤{cfg['gate_latency_ms']}ms）…")
                probe = run_probe(repo_root, backend, args.duration,
                                  cfg["gate_fps"], cfg["gate_latency_ms"])

                if args.browser and chrome is not None:
                    print(f"[{name}] headless 浏览器支路 …")
                    browser = run_browser_leg(backend, chrome,
                                              duration=max(args.duration + 20, 50))
            except Exception as exc:  # noqa: BLE001 —— 单场景失败不拦其余场景
                error = str(exc)

            checks = []
            if error is None and probe is not None:
                checks = evaluate_gates(name, cfg, probe, browser,
                                        cfg["gate_fps"], cfg["gate_latency_ms"])
                scenario_pass = all(ok for _, ok, _ in checks)
            else:
                scenario_pass = False
            all_pass = all_pass and scenario_pass

            entry = {
                "ts": run_stamp,
                "scenario": name,
                "params": {"fps": cfg.get("fps"), "width": cfg.get("width"),
                           "height": cfg.get("height"), "overrides": overrides,
                           "duration": args.duration},
                "probe": probe,
                "browser": browser,
                "checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in checks],
                "pass": scenario_pass,
                "error": error,
            }
            results.append(entry)

            if not args.json:
                status = "PASS" if scenario_pass else "FAIL"
                print(f"[{name}] {status}")
                if probe:
                    e2e = probe.get("e2e_ms", {})
                    print(f"    stamp_fps={probe.get('stamp_fps')} "
                          f"e2e p50={e2e.get('p50')}ms p95={e2e.get('p95')}ms "
                          f"帧间隔 p95={probe.get('frame_interval_ms', {}).get('p95')}ms")
                if browser:
                    print(f"    浏览器: p50={browser.get('e2e_latency_p50_ms')}ms "
                          f"p95={browser.get('e2e_latency_p95_ms')}ms "
                          f"samples={browser.get('e2e_samples')} "
                          f"inbound={browser.get('inbound_fps')}fps "
                          f"jb={browser.get('jitter_buffer_delay_ms')}ms")
                for cname, ok, detail in checks:
                    print(f"    {'✓' if ok else '✗'} {cname}（{detail}）")
                if error:
                    print(f"    错误: {error}")
                    if source is not None:
                        print(f"    合成源日志尾部:\n{source.tail(12)}")
            try:
                args.history.parent.mkdir(parents=True, exist_ok=True)
                with args.history.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except OSError as exc:
                print(f"[警告] 历史写入失败: {exc}", file=sys.stderr)

            if source is not None:
                source.stop()

        if args.compare_last and not args.json:
            entries = load_history(args.history)
            for name in names:
                print_compare(entries, name)

        if not args.json:
            print(f"\n[汇总] {'全部通过' if all_pass else '存在失败'} → 历史 {args.history}")
        else:
            print(json.dumps({"pass": all_pass, "results": results},
                             ensure_ascii=False, indent=2))
        return 0 if all_pass else 1
    finally:
        if own_backend is not None:
            if args.keep_backend:
                print(f"[调试] 隔离后端保留中（pid={own_backend.proc.pid}，日志 {own_backend.log.name}）")
            else:
                own_backend.stop()


if __name__ == "__main__":
    sys.exit(main())
