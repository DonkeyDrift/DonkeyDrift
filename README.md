# DonkeyDrifter

DonkeyDrifter is an open-source Python platform for small-scale autonomous driving and drifting RC cars. Derived from Donkeycar, it keeps the modular Vehicle + Part architecture, the Tub data workflow, neural-network pilot training, and simulator support, while adding a unified Web UI, a launcher service, and first-class integration with the MUS4 ESP32 firmware.

> Independent fork notice: DonkeyDrifter is derived from Donkeycar and is not affiliated with, sponsored by, or endorsed by the Donkeycar maintainers.

## Features

- **Modular vehicle framework**: the Donkeycar Vehicle + Part pipeline (camera, controller, pilot, actuator, datastore, IMU, encoders, and more) with managed drive loops.
- **Car templates**: `basic`, `complete`, `just_drive`, `arduino_drive`, `simulator`, `cv_control`, `path_follow`, `square`, and `train`, created through the `donkey` CLI.
- **Data and training**: Tub recording, local and online training of neural-network pilots, TFLite conversion, and dataset tooling under `scripts/`.
- **Simulator support**: Donkey gym / simulator integration for driving and training without hardware.
- **Unified Web UI**: FastAPI backend plus React/Vite frontend for driving, Tub management, training, connectors, and arena views.
- **Launcher service**: a menu and process-launch service (default port `8090`) that starts the drive stack and Web UI, and serves a browser-based host terminal at `/terminal`.
- **MUS4 firmware integration**: serial Pilot control and telemetry pairing with the ESP32 firmware in the companion [Firmware](https://github.com/DonkeyDrift/Firmware) repository.

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
> The PyPI package `donkeycar` is the upstream Donkeycar project, not DonkeyDrifter.
> Installing it (for example `pip install donkeycar[pc]`) overwrites the `donkeycar`
> compatibility package shipped by DonkeyDrifter and takes over the `donkey` command,
> so DonkeyDrifter commands such as `tui`, `web`, `drive`, and `installweb` disappear.
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

Recommended for new DonkeyDrifter code:

```python
import donkeydrifter as dk
```

Legacy Donkeycar imports continue to work:

```python
import donkeycar as dk
```

Submodule imports are also compatible. New templates prefer `donkeydrifter`, while existing vehicle directories using `donkeycar` do not need to be changed immediately.

## Web UI

DonkeyDrifter includes a unified Web UI under `web_ui/`:

- Backend: FastAPI, default port `8000` (override with `DRIVE_WEB_PORT`).
- Frontend: React/Vite, default port `5188`.
- Integrated startup remains available through:

```bash
donkey installweb --path ./web_ui
donkey web
```

The launcher service (`donkeycar/launcher/`) provides the host menu page on port `8090`, starts the drive stack and Web UI as background processes, and exposes a full host shell in the browser at `/terminal` (xterm.js over a WebSocket↔PTY bridge).

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

DonkeyDrifter is intentionally compatible with existing Donkeycar-based projects during the migration period:

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

## Related Repositories

- [Firmware](https://github.com/DonkeyDrift/Firmware): MUS4 (LP-MU-S4) ESP32 low-level control firmware — RC input capture, driving-mode blending, Park / emergency braking, Drift Assist, Web Console, and OTA.

## License

DonkeyDrifter uses the Apache License 2.0 as its primary project license.

DonkeyDrifter is derived from Donkeycar. Portions originating from Donkeycar remain licensed under the MIT License. See:

- [LICENSE](LICENSE)
- [LICENSES/MIT-donkeycar.txt](LICENSES/MIT-donkeycar.txt)
- [NOTICE](NOTICE)
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)

## Acknowledgements

DonkeyDrifter is derived from the Donkeycar project:

https://github.com/autorope/donkeycar

We thank the Donkeycar maintainers and contributors for their work.

Some historical documentation links may still point to upstream Donkeycar resources. Such links are retained as attribution or compatibility references and may differ from DonkeyDrifter behavior.
