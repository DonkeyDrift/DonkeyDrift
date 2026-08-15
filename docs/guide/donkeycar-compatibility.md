# Donkeycar Compatibility

DonkeyDrifter is derived from Donkeycar and keeps compatibility with existing Donkeycar-based vehicle projects during the migration period.

## PyPI package names and the `donkey` command

Two different distributions are involved and they must not be mixed:

| PyPI name | Project | Provides |
| --- | --- | --- |
| `donkeydrifter` | DonkeyDrifter (this project) | `donkeydrifter` + the `donkeycar` compatibility package + the `donkey` command |
| `donkeycar` | upstream Donkeycar (autorope) | its own `donkeycar` package + its own `donkey` command |

DonkeyDrifter ships the `donkeycar` import name as a compatibility layer. If the
upstream `donkeycar` package is installed afterwards (in any extras variant), pip
overwrites those files and re-generates the `donkey` console script, so the CLI
silently becomes the upstream one. Symptoms:

- `donkey tui`, `donkey web`, `donkey drive`, `donkey installweb` are gone
  (`DonkeyDrifter CLI ... available commands` no longer lists them).
- Running bare `donkey` prints usage instead of starting the DonkeyDrifter TUI.

DonkeyDrifter detects this situation and prints a warning with restore
instructions to stderr whenever `import donkeydrifter` runs. To restore:

```bash
pip uninstall -y donkeycar
pip install "donkeydrifter[macos]"   # macOS
pip install "donkeydrifter[pc]"      # other desktop platforms
# or from a source checkout:
pip install -e ".[pc]"
```

## About `donkeycar[pc]` vs `donkeycar\[pc\]`

These two spellings do **not** differ in what pip installs — the difference is
purely shell-level quoting:

- In bash, a bracket pattern with no matching file is passed through verbatim,
  so `donkeycar[pc]` reaches pip unchanged.
- In zsh (the default shell on macOS), a bare `[pc]` is treated as a glob
  character class; with no matching file the command fails with
  `zsh: no matches found`. Escaping (`\[pc\]`) or quoting (`"donkeycar[pc]"`)
  is required so the brackets reach pip.
- If the backslashes themselves ever reach pip (PowerShell, `cmd`, or text
  copied from Markdown source), pip cannot parse the requirement and treats it
  as a local directory, failing with
  `Directory 'donkeycar\[pc\]' is not installable` — it never installs a
  "different" variant.

So when the `donkey` command behaves differently on macOS after
`pip install donkeycar\[pc\]`, the cause is not the bracket escaping — it is
that this command installs the **upstream** `donkeycar` package, which replaces
the DonkeyDrifter CLI. See the previous section for how to restore
DonkeyDrifter.

## Recommended new import

Use `donkeydrifter` for new DonkeyDrifter code:

```python
import donkeydrifter as dk
```

Submodule imports should also use the new namespace in new templates and new examples:

```python
from donkeydrifter.parts.tub_v2 import TubWriter
from donkeydrifter.vehicle import Vehicle
```

## Legacy import compatibility

Existing Donkeycar-style imports continue to work:

```python
import donkeycar as dk
from donkeycar.parts.tub_v2 import TubWriter
```

This compatibility layer exists so old vehicle directories, tutorials, and user scripts do not need to be migrated immediately.

## CLI compatibility

The CLI command remains `donkey`:

```bash
donkey createcar --path ~/mycar --template complete
donkey web
```

CLI command remains `donkey` for compatibility with existing Donkeycar scripts and documentation.

## What does not change in the first migration stage

- Existing vehicle directories are not modified automatically.
- Existing `donkeycar` imports remain supported.
- Existing `DONKEY_*` configuration keys are not renamed.
- Existing `/api/*` Web UI routes are not renamed.
- Existing drive WebSocket protocol paths are not renamed.

## Migration guidance

New projects should use `donkeydrifter` imports. Existing projects can migrate gradually when convenient. Do not perform blind global replacements in user car directories; test each vehicle project after changing imports.
