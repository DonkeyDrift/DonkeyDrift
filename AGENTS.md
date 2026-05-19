# Donkeycar Agent Guide

This file provides the essential context an AI coding agent needs to work effectively in the Donkeycar repository.

## Project Overview

Donkeycar is a minimalist and modular self-driving library for Python, aimed at hobbyists and students. It provides a pipeline-based vehicle architecture, deep-learning autopilots (TensorFlow and PyTorch), computer vision autopilots, GPS path following, hardware abstraction for cameras/actuators/sensors, and both terminal and web-based user interfaces.

- **Version**: 5.2.0 (defined in `donkeycar/__init__.py`)
- **Python Requirement**: >=3.11.0, <3.12 (enforced at import time in `donkeycar/__init__.py`)
- **License**: MIT
- **Repository**: https://github.com/autorope/donkeycar

## Technology Stack

- **Core**: Python 3.11, NumPy, Pillow, OpenCV, Tornado, pandas, pyyaml
- **Machine Learning**: TensorFlow 2.15, PyTorch 2.1 (optional extras), Keras
- **Data**: pandas, custom "Tub" v2 format for training records
- **Telemetry**: paho-mqtt
- **Terminal UI**: Kivy + rich
- **Web UI Backend**: FastAPI, Uvicorn, python-multipart
- **Web UI Frontend**: React 18.3, TypeScript 5.8, Vite 6, Tailwind CSS 3.4, Zustand 5, Chart.js 4.5, Axios 1.13, react-router-dom 7.13, lucide-react, clsx, tailwind-merge
- **Testing**: pytest, pytest-cov, responses, mypy
- **Build**: setuptools with `setup.cfg` and `pyproject.toml`

## Project Structure

```
donkeycar/
  __init__.py          # Package init; sets version, recursion limit, imports Vehicle/Memory
  vehicle.py           # Core Vehicle drive loop and PartProfiler
  memory.py            # Memory bus for inter-part communication
  config.py            # Config loader (config.py + optional myconfig.py overlay)
  utils.py             # Image/array helpers, model type resolution
  geom.py, la.py       # Geometry and linear algebra utilities
  parts/               # Hardware drivers, controllers, neural nets, CV, data stores
    camera.py          # PiCamera (picamera2), Webcam, CSICamera, MockCamera, etc.
    actuator.py        # PWM steering/throttle, H-Bridge, VESC, PCA9685
    controller.py      # Joystick, Web, RC, Mock controllers
    keras.py           # KerasPilot base class and model architectures
    pytorch/           # PyTorch models and training
    tub_v2.py          # Tub v2 data storage (manifest + records + images)
    datastore_v2.py    # Lower-level tub v2 data primitives
    image_transformations.py  # Crop, trapeze, blur, resize, color-space transforms
    network.py, telemetry.py, gps.py, lidar.py, imu.py, ...
    simulation.py      # Mock camera/telemetry for testing
    web_controller/    # Tornado-based web controller
    object_detector/   # Object detection parts
    voice_control/     # Voice control parts
  pipeline/            # Training pipeline
    training.py        # TensorFlow training entry point (BatchSequence, train())
    sequence.py        # TubRecord, TubSequence, TfmIterator
    augmentations.py   # Albumentations-based image augmentation
    types.py           # TubDataset and type definitions
    database.py        # PilotDatabase for tracking trained models
  management/          # CLI tooling and UIs
    base.py            # donkey CLI command dispatcher (createcar, train, calibrate, ...)
    train_local.py, train_online.py
    ui/                # Kivy-based GUI
    tui.py             # Terminal UI (rich-based)
    tub_web/           # Legacy Bootstrap/jQuery tub browser
  templates/           # Car application templates and default configs
    complete.py        # Full-featured car script (the default template)
    cfg_complete.py    # Default configuration values
    basic.py, simulator.py, path_follow.py, cv_control.py, ...
    train.py, calibrate.py, myconfig.py
  tests/               # Unit tests (pytest)
  utilities/           # Circular buffer, platform detection, etc.
  gym/                 # OpenAI Gym / DonkeyGym simulator integration
  contrib/             # Community hardware contributions
web_ui/
  backend/             # FastAPI app
    main.py            # FastAPI app with CORS
    trainer_engine.py  # TrainingJobManager for local/online jobs and SSE streaming
    web_online_trainer.py  # OnlineTrainer subclass for web log streaming
    routers/
      config.py        # /api/config — directory picker, config loader
      tub.py           # /api/tub — load tub, get records, serve images, delete/restore
      trainer.py       # /api/trainer — training config, start/stop, job status, SSE logs
    requirements.txt   # fastapi, uvicorn, python-multipart, pandas, numpy, pillow
  frontend/            # React + Vite SPA
    package.json       # Dependencies and scripts
    src/App.tsx        # Router (/ , /trainer)
    src/components/    # TubEditor, TubNavigator, ConfigLoader, TrainerPage components
    src/pages/         # Home, TrainerPage
    src/store/         # Zustand store, Axios API client
    src/services/      # API client functions
    src/hooks/         # Custom React hooks
tests/                 # Top-level integration tests
scripts/               # Standalone utilities (tflite conversion, profiling, migration, etc.)
arduino/               # Arduino firmware for encoders
docs/                  # Architecture and design documentation
  arch/                # Architecture notes (web controller, params persistence, etc.)
  plan/                # Design plans (trainer-design, etc.)
```

## Build, Install, and Test Commands

### Installation

The project uses `setuptools` with `setup.cfg` and `pyproject.toml`.

```bash
# Base install (core dependencies only)
pip install -e .

# PC development (includes TensorFlow, matplotlib, Kivy, albumentations)
pip install -e .[pc,dev]

# Raspberry Pi
pip install -e .[pi,dev]

# Jetson Nano
pip install -e .[nano,dev]

# macOS (with tensorflow-metal)
pip install -e .[macos,dev]

# PyTorch support
pip install -e .[torch]
```

Core dependencies (from `setup.cfg`): `numpy`, `pillow`, `docopt`, `tornado`, `requests`, `PrettyTable`, `paho-mqtt`, `simple_pid`, `progress`, `pyfiglet`, `psutil`, `pynmea2`, `pyserial`, `utm`, `pandas`, `pyyaml`, `rich`, `paramiko`.

### Testing

```bash
# Run all tests (from repo root)
pytest

# Run with coverage (configured in .coveragerc; omits donkeycar/tests/*)
pytest --cov

# The Makefile also exposes:
make tests
```

Test configuration lives in `donkeycar/tests/pytest.ini`:
- Deprecation and Future warnings are ignored.
- `log_cli = True` at INFO level.
- `reruns = 3` (flakiness mitigation).

Coverage configuration (`.coveragerc`):
- Branch coverage enabled.
- Omits `donkeycar/tests/*` from coverage metrics.

### Linting / CI

- GitHub Actions runs `pytest` on `ubuntu-latest` and `macos-latest` using conda/mamba with Python 3.11.
  - Workflow: `.github/workflows/python-package-conda.yml`
  - Installs with `pip install -e .[pc,dev]` then runs `pytest`.
- Super-Linter runs on push/PR (non-blocking, `continue-on-error: true`, `DISABLE_ERRORS: true`).
  - Workflow: `.github/workflows/superlinter.yml`
  - Excludes `*.css` and `*.js` files.
- No dedicated local linter configs (`.flake8`, `.pylintrc`, `.pre-commit-config.yaml`) are present.

## Code Style Guidelines

- Follow **PEP-8**.
- Keep data and methods arranged in classes where possible.
- Avoid lengthy monolithic functions, excessive parameters, and monkey-patching.
- Add comments where behavior is non-obvious.
- The project targets Raspberry Pi OS, Jetson Nano, Linux, macOS, and WSL on Windows.
- New features should have **unit tests** and be broadly useful to the community.
- Config values are **UPPERCASE** by convention.

## Key Architectural Patterns

### Vehicle / Part / Memory Pattern

This is the heart of Donkeycar. A `Vehicle` runs a loop at a configured Hz. Each hardware or software component is a **Part**.

- `Vehicle.add(part, inputs=[], outputs=[], threaded=False, run_condition=None)`
- Parts must implement at minimum:
  - `run(*inputs)` — synchronous execution.
  - Optionally `run_threaded(*inputs)` — if `threaded=True`.
  - Optionally `update()` — background thread loop.
  - Optionally `shutdown()` — cleanup on exit.
- Parts communicate via named channels in a `Memory` object (a dict-like store).
- Example: a camera part outputs `["cam/image_array"]`, a tub writer inputs it.

### Configuration System

Config is loaded from `config.py`, then overlaid with `myconfig.py` (if present). Uppercase attributes become config values. Users customize their car by uncommenting and editing values in `myconfig.py`.

```python
from donkeycar import load_config
cfg = load_config('~/mycar/config.py')
```

### Templates and Car Creation

`donkey createcar --path ~/mycar --template complete` copies template files into a user directory:
- `manage.py` (car application)
- `config.py` + `myconfig.py` (configuration)
- `train.py`, `calibrate.py`

The default `complete.py` template constructs a full vehicle pipeline: camera → controller → AI model → drivetrain → tub writer.

### Data Storage (Tub v2)

Training data is stored in **Tubs**: directories containing:
- `manifest.json` — schema and metadata
- `images/` — JPEG images
- Record files — JSON lines of sensor data

Access via `donkeycar.parts.tub_v2.Tub`.

### Training Pipeline

1. `donkey train --tub <paths> --model <name> --type <model_type>`
2. `donkeycar.management.base.Train` dispatches to:
   - TensorFlow: `donkeycar.pipeline.training.train()`
   - PyTorch: `donkeycar.parts.pytorch.torch_train.train()`
3. Models are looked up by type string (e.g., `linear`, `categorical`, `resnet18`) via `donkeycar.utils.get_model_by_type()`.
4. Post-training, optional `.tflite` and `.trt` conversions are performed.
5. Training metadata is stored in a `PilotDatabase` (JSON in the car directory).

### Web UI

A modern web interface is provided under `web_ui/`:
- **Backend**: FastAPI with CORS enabled (`allow_origins=["*"]`). Routers: `/api/config`, `/api/tub`, `/api/trainer`.
- **Frontend**: React SPA served by Vite. Communicates with backend via REST and SSE for training log streaming.
- Launch via: `donkey web --path <web_ui_dir> --frontend-port 5188 --backend-port 8000`
- The CLI command spawns both `uvicorn` (backend) and `npm run dev` (frontend) as subprocesses.
- Supports both **local training** (subprocess `donkey train`) and **online/cloud training** (SSH to remote server, upload data, run training, download model).

### Legacy Web Controller

The Tornado-based web controller lives in `donkeycar/parts/web_controller/`:
- Provides remote driving, calibration, and MJPEG video streaming.
- Default port `8887` for the full controller; `8890` for FPV-only mode.
- Static assets are served from `donkeycar/parts/web_controller/templates/static/`.

## Entry Points and CLI

The `donkey` console command is defined in `setup.cfg`:

```
donkey = donkeycar.management.base:execute_from_command_line
```

Available subcommands (from `management/base.py`):
- `createcar` — scaffold a new car directory
- `update` — update car files from templates
- `train` — train an autopilot
- `calibrate` — calibrate PWM/servo
- `tubhist` / `tubplot` — data visualization
- `makemovie` — generate video from tub
- `models` — show model database
- `ui` / `tui` — graphical/terminal UIs
- `web` — launch the new web UI

## Testing Instructions

- Place unit tests in `donkeycar/tests/`.
- Place integration tests in `tests/` at the project root.
- Use fixtures from `donkeycar/tests/setup.py` for sample tubs, cars, and records.
  - `tub_path`, `tub`, `tubs` — pytest fixtures for temporary tub directories.
  - `create_sample_tub(path, records=128)` — programmatically populate a tub.
  - `default_template(car_dir)`, `custom_template(car_dir, template)` — scaffold a car directory.
  - `create_sample_record()` — generate a single mocked record.
  - `on_pi()` — platform detection for Raspberry Pi guards.
- Mock hardware when possible; many tests use `SquareBoxCamera` and `MovingSquareTelemetry` from `donkeycar.parts.simulation`.
- Platform-specific tests should guard with `on_pi()` or similar checks (e.g., `@pytest.mark.skipif(on_pi() == False, reason='Not on RPi')`).
- Both **pytest** and **unittest** patterns exist in the codebase; prefer pytest for new tests.
- Use `tempfile.mkdtemp()` or `tmpdir` pytest fixtures for isolated test data, and clean up after tests.
- Training tests in `donkeycar/tests/test_train.py` verify model convergence and pipeline consistency.
- Web UI scripts in `web_ui/test_*.py` are ad-hoc API probing scripts (not pytest tests); they make live HTTP calls to `localhost:8000`.

## Security and Safety Considerations

- This project controls physical hardware (motors, servos). Test changes in `MOCK` drivetrain mode or simulator (`DONKEY_GYM`) before deploying to a real vehicle.
- The web controller and Web UI bind to `0.0.0.0` by default; ensure network exposure is intentional.
- The FastAPI backend in `web_ui/backend` uses `allow_origins=["*"]` for development.
- Be cautious with subprocess calls in `management/base.py` (port scanning, npm, uvicorn).

## Notes for AI Agents

- **Do not assume hardware availability**. Most development happens on PC/Mac; use mock parts or simulators for testing.
- **Respect the Part interface** when adding new components: implement `run()`, and optionally `run_threaded()`, `update()`, `shutdown()`.
- **Config values are uppercase** by convention. Custom config should be added to `cfg_complete.py` and documented.
- **Avoid breaking Tub v2 format changes** — it is the primary data interchange format.
- When editing the web UI, remember both the FastAPI backend (`web_ui/backend/`) and the React frontend (`web_ui/frontend/`).
- The `docs/` directory contains architecture notes (`docs/arch/`) and design plans (`docs/plan/`) that may provide useful context for complex features.
