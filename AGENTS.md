# DonkeyDrifter Agent Guide

This file provides the essential context an AI coding agent needs to work effectively in the DonkeyDrifter repository. The project is an independent Python autonomous driving / drifting robotics platform derived from Donkeycar. All facts below are taken from the actual files in the working tree (current branch `WebRTC-v1.4`, version `0.1.1`).

## Project Overview

- **Version**: `0.1.1` defined in `donkeycar/_version.py`.
- **Python Requirement**: `>=3.11.0,<3.12`.
- **Primary distribution package**: `donkeydrifter` (setuptools metadata lives in `setup.cfg`).
- **Implementation package**: `donkeycar/` (legacy compatibility namespace).
- **Recommended import**: `import donkeydrifter as dk`.
- **Compatibility import**: `import donkeycar as dk` still works via a `sys.meta_path` alias in `donkeydrifter/__init__.py`.
- **CLI entry point**: `donkey = donkeycar.management.base:execute_from_command_line`.
- **License**: Apache License 2.0 for DonkeyDrifter changes; upstream Donkeycar portions remain MIT. See `LICENSE`, `NOTICE`, `THIRD_PARTY_NOTICES.md`, and `LICENSES/MIT-donkeycar.txt`.
- **Repository**: https://gitee.com/ffedu/donkeydrifter
- **Upstream source**: https://github.com/autorope/donkeycar

DonkeyDrifter is not affiliated with, sponsored by, or endorsed by the Donkeycar maintainers.

## Repository Layout

```text
donkeydrifter/       # Public alias package that forwards imports to donkeycar/
donkeycar/           # Current implementation package + legacy compat namespace
  __init__.py        # Enforces Python >=3.11, exposes Vehicle, Memory, load_config
  _version.py        # __version__ = '0.1.1'
  vehicle.py         # Vehicle drive loop and PartProfiler
  memory.py          # Key/value bus for inter-part communication
  config.py          # Config loader
  parts/             # 70+ hardware/algorithm Parts (camera, controller, keras, pytorch, tub_v2, IMU, GPS, drive_api_bridge, ...)
  pipeline/          # Training pipeline, augmentations, sequence handling, database
  management/        # CLI tooling and UIs (base.py, tui.py, train_*.py, ui/, tub_web/)
  templates/         # Vehicle app templates used by `donkey createcar`
  tests/             # Core unit/integration tests (~49 files)
  utilities/         # Helpers and TrackSpeedPlanner
  contrib/, gym/     # Community and simulator integrations
web_ui/              # Unified FastAPI backend + React/Vite frontend
  backend/main.py    # FastAPI app mounting /api/{config,tub,trainer,drive,arena,connector}
  backend/routers/   # FastAPI route modules
  backend/tests/     # FastAPI contract tests
  frontend/src/      # React/TypeScript/Vite SPA
parts/               # Additional top-level Part (drive_api_bridge.py)
tests/               # Root-level migration/integration tests
scripts/             # Standalone utilities (convert, freeze, profile, ...)
arduino/             # mono_encoder & quadrature_encoder sketches
docs/                # Architecture, plans, guides, validation, superpowers specs
```

## Technology Stack

- **Core runtime**: Python 3.11, NumPy, Pillow, OpenCV, Tornado, pandas, PyYAML, requests.
- **Machine Learning**: TensorFlow `2.15.*`, Keras; PyTorch `2.1.*`, pytorch-lightning, torchvision, fastai `<2.8`.
- **Data format**: Tub v2 (manifest + catalogs + images); logic in `donkeycar/parts/tub_v2.py`.
- **Telemetry**: paho-mqtt.
- **Terminal UI**: rich, Kivy (`.kv` files included as package data).
- **Web UI backend**: FastAPI, Uvicorn, Pydantic, python-multipart, websockets, aiortc, av.
- **Web UI frontend**: React 18, TypeScript ~5.8, Vite 6, Tailwind CSS 3, Zustand, Chart.js, axios, react-router-dom 7.
- **Testing**: pytest, pytest-cov, responses, mypy; frontend vitest + jsdom + Playwright.
- **Build / packaging**: setuptools via `setup.cfg` + `pyproject.toml`; `python -m build` for wheels/sdists.

## Build, Install, and Run Commands

Install the package for local development (choose the platform extra matching your machine):

```bash
# PC / Linux / WSL
pip install -e ".[pc,dev]"

# macOS with Apple Silicon/Metal
pip install -e ".[macos,dev]"

# Raspberry Pi
pip install -e ".[pi,dev]"

# Jetson Nano
pip install -e ".[nano,dev]"
```

Web UI one-time dependency install:

```bash
donkey installweb --path ./web_ui
# or
make installweb
```

This installs backend Python deps from `web_ui/backend/requirements.txt` and runs `npm install` in `web_ui/frontend`.

Run the unified Web UI:

```bash
donkey web --path ./web_ui
# With auto-install of missing deps and browser open:
donkey web --path ./web_ui --install-deps --open
```

Run core tests:

```bash
pytest
pytest donkeycar/tests/test_vehicle.py -q
```

Run Web UI backend tests:

```bash
cd web_ui/backend
python -m pytest tests -q
```

Run Web UI frontend checks:

```bash
cd web_ui/frontend
npm run check   # tsc --noEmit
npm run lint    # eslint .
npm run build
npm run test    # vitest
```

Build a release:

```bash
python -m build --sdist --wheel
# or
make package
```

Run the full test target:

```bash
make tests   # runs pytest
```

### CLI commands provided by `donkey`

Registered in `donkeycar/management/base.py`:

- `createcar` – generate a vehicle directory from templates.
- `update` – refresh vehicle files in the current directory.
- `findcar` – discover car IP on the local network.
- `calibrate` – PWM/servo calibration.
- `train` – training entry point.
- `tubplot`, `tubhist`, `makemovie`, `cnnactivations` – data visualization.
- `models` – model database.
- `ui`, `tui` – GUIs; bare `donkey` defaults to TUI.
- `web` – launch unified FastAPI + React Web UI.
- `installweb` – install Web UI backend/frontend dependencies.
- `createjs` – joystick creator.

## Development Conventions

### Import compatibility contract

- New code and templates should prefer `import donkeydrifter as dk`.
- Existing `import donkeycar` must remain compatible; do not break the alias layer in `donkeydrifter/__init__.py`.
- The CLI command must stay `donkey`.
- Existing `DONKEY_*` configuration keys are not renamed in the first migration stage.
- Existing Web UI `/api/*` routes and drive WebSocket protocols are not renamed in the first migration stage.
- Do not blindly replace every Donkeycar reference; upstream attribution, compatibility docs, and license text must keep the Donkeycar name where appropriate.

### Vehicle / Part / Memory architecture

- `Vehicle` (`donkeycar/vehicle.py`) is the main loop container.
- Parts are registered with `Vehicle.add(part, inputs=[], outputs=[], threaded=False, run_condition=None)`.
- Each loop tick reads named `inputs` from `Memory`, invokes `part.run()` (or `part.update()` in a background thread for `threaded=True`), and writes named `outputs` back.
- `Memory` (`donkeycar/memory.py`) is a simple key/value bus. Parts communicate via string keys, not direct references.
- Parts use duck-typing: implement `run()`; threaded Parts also implement `update()`; cleanup goes in `shutdown()`. Avoid multiple Parts writing the same Memory key concurrently.

### Code style

- **Python**: `CONTRIBUTING.md` references PEP-8. Black configuration exists at `.github/linters/.python-black` (`line-length = 80`, `target-version = ['py37']`, `skip-string-normalization = true`), used primarily by the GitHub Super-Linter.
- **TypeScript**: `tsconfig.json` uses `module: ESNext`, `moduleResolution: bundler`, `jsx: react-jsx`, `strict: false`, path alias `@/* -> ./src/*`.
- **ESLint**: `eslint.config.js` uses `typescript-eslint` recommended, `react-hooks` recommended, and `react-refresh/only-export-components` as a warning.
- **Tailwind**: `tailwind.config.js` uses `darkMode: "class"` and content paths `./index.html` and `./src/**/*`.

### Web UI conventions

- Backend entry point: `web_ui/backend/main.py` (default port `8000`).
- Frontend dev server: `web_ui/frontend` (default port `5188`, Vite proxies `/api` to `http://localhost:8000`).
- Frontend API client is centralized in `web_ui/frontend/src/services/api.ts`; do not hardcode API base URLs elsewhere. `VITE_API_BASE_URL` can override the base URL.
- Video transport can be forced with `VITE_DRIVE_VIDEO_TRANSPORT=webrtc|mjpeg`; default is auto.
- Production build is a static SPA using HashRouter (`/#/drive`, `/#/trainer`, etc.).

## Testing Instructions

- **Core Python tests**: `pytest` (picks up `donkeycar/tests/` and `tests/`). `donkeycar/tests/pytest.ini` suppresses deprecation warnings, enables CLI logs at INFO, and sets `reruns = 3`.
- **Coverage**: `.coveragerc` enables branch coverage and omits `donkeycar/tests/*`.
- **Root-level integration tests**: `pytest tests/ -q` covers migration branding, restore logic, model naming refactor, online trainer workspace, tub manager refresh.
- **Web UI backend tests**: `cd web_ui/backend && python -m pytest tests -q` covers drive (WebRTC/MJPEG/stats), connector, arena, config, and branding.
- **Web UI frontend tests**: `cd web_ui/frontend && npm run test` runs vitest in jsdom. Playwright-style tests also exist under `web_ui/frontend/testsprite_tests/`.

## Security Considerations

- The FastAPI backend in `web_ui/backend/main.py` configures CORS with `allow_origins=["*"]`, `allow_credentials=True`, `allow_methods=["*"]`, `allow_headers=["*"]` for local development. This is intentionally permissive for LAN prototyping; do not expose the Web UI directly to untrusted networks without adding authentication or restricting origins.
- There is no built-in authentication layer on the Web UI or WebSocket control channel. Anyone with network access to the car/backend can send drive commands, view the video stream, and start/stop training.
- WebRTC signaling and MJPEG fallback video are local-network features. Consider network segmentation before running on public or shared Wi-Fi.
- Car-side templates and `myconfig.py` may contain hardware credentials or pins. Treat generated vehicle directories as sensitive if they include SSH/MQTT or cloud keys.
- Do not commit secrets, `node_modules`, or build artifacts. The repository already excludes them via `.gitignore`.

## Deployment and Packaging

- **setuptools packaging**: `python -m build --sdist --wheel` (or `make package`) produces `donkeydrifter-<version>-py3-none-any.whl` and `donkeydrifter-<version>.tar.gz`. CI runs `twine check dist/*` before publishing.
- **PyPI publish**: `.github/workflows/publish-pypi.yml` triggers on tags `v*` and publishes via OIDC.
- **CI / testing**: `.github/workflows/python-package-conda.yml` runs on push/PR across `macos-latest` and `ubuntu-latest`, creates a Python 3.11 conda env, installs `.[pc,dev]`, verifies both `donkeydrifter` and `donkeycar` imports, builds the package, and runs `pytest`. `.github/workflows/superlinter.yml` runs the GitHub Super-Linter in non-blocking mode.
- **Docker**: The top-level `Dockerfile` exists but is currently stale. It uses `python:3.6`, references a non-existent `setup.py` and `[tf]` extra, and targets Jupyter rather than the FastAPI/React Web UI. Treat it as legacy unless it is explicitly updated.

## Migration Contract

During the DonkeyDrifter migration:

- New code and templates should prefer `donkeydrifter` imports.
- Existing `donkeycar` imports must remain compatible.
- The CLI command remains `donkey`.
- Existing `DONKEY_*` configuration keys are not renamed in the first migration stage.
- Existing Web UI `/api/*` routes and drive WebSocket protocols are not renamed in the first migration stage.
- Upstream Donkeycar attribution and MIT License text must not be removed.

## Important Agent Notes

- When editing templates, new generated vehicle apps should use `import donkeydrifter as dk`.
- When editing Web UI routes, keep `/api` contracts stable unless a separate migration plan changes them.
- When changing license or attribution files, keep `LICENSE`, `NOTICE`, `THIRD_PARTY_NOTICES.md`, and `LICENSES/MIT-donkeycar.txt` consistent.
- TensorFlow is pinned to `2.15.*` and PyTorch to `2.1.*`; major bumps affect model compatibility.
- Tub v2 is the canonical data format; recording logic is centralized in `donkeycar/parts/tub_v2.py`.
- CLI template files are both user-generated app sources and configuration contracts; changes to templates often need matching updates in `cfg_*.py` files and tests.
- The car-side Web UI bridge is `parts/drive_api_bridge.py` (`DriveApiBridge`), a threaded Part that replaces the legacy Tornado `LocalWebController` and pushes state/video to the FastAPI backend over WebSocket.

## Useful References

- `README.md` – quick start and compatibility summary.
- `CLAUDE.md` – extended Chinese-language guidance for Claude Code, including command cheatsheets and architecture notes.
- `docs/guide/donkeycar-compatibility.md` – dual-import compatibility guide.
- `docs/guide/web-drive-console-user-guide.md` – Drive page user guide.
- `docs/plan/donkeydrifter-v0.1.0-release-notes.md` – validation results and release notes.
- `docs/plan/web-drive-console-migration.md` and `docs/plan/drive-api-bridge-migration.md` – migration design docs.
