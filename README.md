# DonkeyDrift

DonkeyDrift is a Python autonomous driving and drifting robotics platform derived from Donkeycar. It keeps the modular Vehicle + Part architecture, Tub data workflow, training tools, simulator support, and Web UI workflows while establishing an independent DonkeyDrift identity.

> Independent fork notice: DonkeyDrift is derived from Donkeycar and is not affiliated with, sponsored by, or endorsed by the Donkeycar maintainers.

## Features

- **Modular vehicle framework**: the Donkeycar Vehicle + Part pipeline (camera, controller, pilot, actuator, datastore, IMU, encoders, and more) with managed drive loops.
- **Car templates**: `basic`, `complete`, `just_drive`, `arduino_drive`, `simulator`, `cv_control`, `path_follow`, `square`, and `train`, created through the `donkey` CLI.
- **Data and training**: Tub recording, local and online training of neural-network pilots, TFLite conversion, and dataset tooling under `scripts/`.
- **Simulator support**: Donkey gym / simulator integration for driving and training without hardware.
- **Unified Web UI**: FastAPI backend plus React/Vite frontend for driving, Tub management, training, connectors, and arena views.
- **Launcher service**: a menu and process-launch service (default port `8090`) that starts the drive stack and Web UI, and serves a browser-based host terminal at `/terminal`.
- **MUS4 firmware integration**: serial Pilot control and telemetry pairing with the ESP32 firmware in the companion [Firmware](https://github.com/DonkeyDrift/Firmware) repository.
- **Overhead drift control**: an overhead USB camera tracks an AprilTag on the car roof, estimates field-coordinate pose and drift angle β, records synchronized telemetry tubs, and later closes the loop with a cascaded PID + throttle-pulse controller — see the [中文章节](#俯拍漂移监控系统-overhead-drift-control) below.

## Quick Start

```bash
pip install "donkeydrifter[pc]"
donkey createcar --path ~/mycar --template complete
cd ~/mycar
python manage.py drive
```

The CLI command remains `donkey` for compatibility with the Donkeycar ecosystem and existing vehicle projects.

Requires Python 3.11.

> **Important: install `donkeydrifter`, never `donkeycar`.**
> The PyPI package `donkeycar` is the upstream Donkeycar project, not DonkeyDrift.
> Installing it (for example `pip install donkeycar[pc]`) overwrites the `donkeycar`
> compatibility package shipped by DonkeyDrift and takes over the `donkey` command,
> so DonkeyDrift commands such as `tui`, `web`, `drive`, and `installweb` disappear.
> If this happens, restore with:
>
> ```bash
> pip uninstall -y donkeycar
> pip install "donkeydrifter[macos]"   # macOS
> pip install "donkeydrifter[pc]"      # other desktop platforms
> ```

### Platform extras

- `pc` — desktop platforms (TensorFlow, matplotlib, Kivy UI, training stack, Web UI backend).
- `macos` — same as `pc` plus `tensorflow-metal` for Apple Silicon GPU acceleration.

On macOS the default shell is zsh, which treats bare `[...]` as a glob pattern and fails
with `no matches found`. Quote the requirement instead of escaping the brackets
(`pip install donkeycar\[pc\]` and `pip install donkeycar[pc]` install the same thing —
the brackets must simply survive the shell):

```bash
pip install "donkeydrifter[macos]"    # zsh (macOS default), quoted form
pip install donkeydrifter\[macos\]    # zsh, escaped form (equivalent)
pip install donkeydrifter[macos]      # bash / GitHub Actions
```

For local development:

```bash
git clone https://github.com/DonkeyDrift/DonkeyDrift.git
cd DonkeyDrift
pip install -e ".[pc,dev]"
pytest
```

## Python Imports

Recommended for new DonkeyDrift code:

```python
import donkeydrifter as dk
```

Legacy Donkeycar imports continue to work:

```python
import donkeycar as dk
```

Submodule imports are also compatible. New templates prefer `donkeydrifter`, while existing vehicle directories using `donkeycar` do not need to be changed immediately.

## Web UI

DonkeyDrift includes a unified Web UI under `web_ui/`:

- Backend: FastAPI, default port `8000` (override with `DRIVE_WEB_PORT`).
- Frontend: React/Vite, default port `5188`.
- Integrated startup remains available through:

```bash
donkey installweb --path ./web_ui
donkey web
```

The launcher service (`donkeycar/launcher/`) provides the host menu page on port `8090`, starts the drive stack and Web UI as background processes, and exposes a full host shell in the browser at `/terminal` (xterm.js over a WebSocket↔PTY bridge).

## 俯拍漂移监控系统 (Overhead Drift Control)

俯拍漂移监控系统是 Web UI Drive 页的功能子系统（「第三视角漂移」卡片）：笔记本端 USB 俯拍相机实时检测车顶 AprilTag，解算场地坐标位姿与漂移角 β，支撑人工漂移数据录制、点动机理离线分析，以及后续的自动定圆漂移闭环。**人工控制始终走 RC 遥控器（ESP32 本地），笔记本只接管、随时可夺回。**

系统链路：

```text
笔记本（FastAPI :8000 后端 + React 前端 + USB 俯拍相机，检测 AprilTag → 位姿 → β → 级联 PID + 油门脉冲）
   ⇅ WebSocket
车端 SBC（donkeycar manage.py，主动回连笔记本，上报 rc/IMU 遥测）
   ⇅ 串口
ESP32（MUS4 固件，RC 遥控器本地控制）
```

核心能力：

- **视觉位姿**：AprilTag tag36h11 检测（半分辨率快速路径 + 全分辨率自适应重试），经场地单应性映射场地坐标（西南原点、X 东 Y 北、heading 逆时针为正）；跳变拒绝带持续离群恢复。
- **β 估计**：heading 域互补滤波（视觉差分 + 陀螺 gz 积分），静止 0.3 s 衰减归零。
- **实时预览**：60 fps WebRTC 推流（MJPEG 兜底），叠加绿框、车头红箭、2 s 速度着色轨迹（绿→黄→红）与深蓝 β 航迹箭；`camera_fps`/`read_ms`/`detect_ms`/`tag_hits` 分段诊断指标。
- **同步录制**：以相机帧时戳为基准对齐 ws 遥测流（rc 60 Hz / IMU 100 Hz）线性插值，tub v2 格式落盘，在线提取油门点动特征（频率/占空比/幅值）。
- **控制与安全**：级联 PID + 油门脉冲发生器、看门狗（丢帧/断线时零油门）、AUTO 期间服务端多 client 仲裁（浏览器控制字段一律丢弃并回发 `control_rejected`）。

模块地图（`web_ui/backend/`，254 例测试全绿）：

| 模块                                       | 职责                                                |
| ------------------------------------------ | --------------------------------------------------- |
| `drift_vision.py`                          | 单应性/位姿解算、USB 相机（手动曝光）、检测、叠加绘制 |
| `state_estimator.py`                       | β 估计（互补滤波 + 静止衰减）                        |
| `drift_controller.py`                      | 级联 PID、油门脉冲发生器、看门狗                     |
| `drift_session.py`                         | 会话状态机（观察 → β 稳定 → 接管）                   |
| `sync_recorder.py`                         | 遥测插值对齐 + tub v2 录制                           |
| `drift_engine.py`                          | 编排：相机循环、分段计时、命中率计数                  |
| `routers/drive.py` / `routers/drift.py`    | 驾驶 ws 与控制仲裁、REST API                        |
| `drift_webrtc.py`                          | aiortc 60 fps 推流（360p）                           |
| `web_ui/frontend/.../DriftCard.tsx`        | 前端卡片（预览、参数面板、localStorage 回填）         |

当前状态（2026-08-30）：**M0 相机链路已收官**——60 fps 稳定、运动丢检测排障闭环（曝光 1/400 s 根治拖影）；M1 人工漂移录制、M2 点动机理验证待实操。里程碑与验收标准见[实施计划](docs/plan/overhead-drift-control-implementation.md)与[状态交接文档](docs/guide/overhead-drift-handoff.md)。

## Repository Layout

- [`donkeycar/`](donkeycar/): main Python package — vehicle framework, parts, templates, management CLI, launcher, and tests.
- [`donkeydrifter/`](donkeydrifter/): alias package that re-exports `donkeycar` and maps `donkeydrifter.*` submodule imports onto it.
- [`web_ui/`](web_ui/): Web UI — FastAPI backend (`web_ui/backend/`) and React/Vite frontend (`web_ui/frontend/`).
- [`docs/`](docs/): guides, architecture notes, RFCs, and plans.
- [`scripts/`](scripts/): standalone utilities (training aids, TFLite conversion, profiling, visualization).
- [`tests/`](tests/): top-level tests.
- [`arduino/`](arduino/): Arduino encoder sketches used by the `arduino_drive` template.

## Development

Common commands:

```bash
pytest
pytest donkeycar/tests/test_vehicle.py -q
python -m build --sdist --wheel
```

Web UI backend:

```bash
cd web_ui/backend
python -m pytest tests -q
```

Web UI frontend:

```bash
cd web_ui/frontend
npm run check
npm run lint
npm run build
```

## Compatibility with Donkeycar

DonkeyDrift is intentionally compatible with existing Donkeycar-based projects during the migration period:

- `pip install donkeydrifter` is the new package target.
- `import donkeydrifter as dk` is the recommended import path for new code.
- `import donkeycar as dk` remains supported as a compatibility path.
- The CLI command remains `donkey`.
- Existing vehicle projects can migrate gradually.
- Existing `/api/*` Web UI paths and drive WebSocket protocols are not renamed in the first migration stage.

See the [Donkeycar compatibility guide](docs/guide/donkeycar-compatibility.md) for details.

## Documentation

- [Donkeycar compatibility guide](docs/guide/donkeycar-compatibility.md)
- [Web drive console user guide](docs/guide/web-drive-console-user-guide.md)
- [License and attribution](docs/guide/license-and-attribution.md)
- [Parallel development with worktrees](docs/guide/parallel-development-with-worktrees.md)
- [俯拍漂移控制 RFC（总体设计）](docs/Rfc/overhead-drift-control.md)
- [俯拍漂移控制实施计划（M0~M5）](docs/plan/overhead-drift-control-implementation.md)
- [俯拍漂移实操手册](docs/guide/overhead-drift-first-run.md)
- [俯拍漂移状态交接（当前状态+踩坑记录）](docs/guide/overhead-drift-handoff.md)

## Related Repositories

- [Firmware](https://github.com/DonkeyDrift/Firmware): MUS4 (LP-MU-S4) ESP32 low-level control firmware — RC input capture, driving-mode blending, Park / emergency braking, Drift Assist, Web Console, and OTA.

## License

DonkeyDrift uses the Apache License 2.0 as its primary project license.

DonkeyDrift is derived from Donkeycar. Portions originating from Donkeycar remain licensed under the MIT License. See:

- [LICENSE](LICENSE)
- [LICENSES/MIT-donkeycar.txt](LICENSES/MIT-donkeycar.txt)
- [NOTICE](NOTICE)
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)

## Acknowledgements

DonkeyDrift is derived from the Donkeycar project:

https://github.com/autorope/donkeycar

We thank the Donkeycar maintainers and contributors for their work.

Some historical documentation links may still point to upstream Donkeycar resources. Such links are retained as attribution or compatibility references and may differ from DonkeyDrift behavior.
