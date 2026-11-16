"""Shared DonkeyDrift uv install-step builder.

Stdlib-only module so it can run on a fresh machine without the backend
venv: it is consumed both by the SSH-driven My-PC installer
(``mypc_installer``) and by the local one-click deployer
(``scripts/one_click_deploy.py``). It builds the same nine idempotent
install steps for macOS Apple Silicon (zsh) and Windows (PowerShell).
"""
import base64
import gzip
import ntpath
import posixpath
import re
import shlex
from dataclasses import dataclass

UV_INDEX = "https://pypi.tuna.tsinghua.edu.cn/simple"
UV_PYTHON_MIRROR = "https://mirror.nju.edu.cn/github-release/astral-sh/python-build-standalone"
GYM_REPOSITORY = "https://github.com/tawnkramer/gym-donkeycar"
INSTALL_TIMEOUT = 3600
PINS = (
    "numpy==1.26.4",
    "scipy==1.17.1",
    "opencv-python-headless==4.11.0.86",
    "gymnasium==1.3.0",
)
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_HOOK_START = "# >>> donkeydrift-auto-activate >>>"
_HOOK_END = "# <<< donkeydrift-auto-activate <<<"


@dataclass(frozen=True)
class InstallStep:
    name: str
    command: str


def _clean_line(raw: str) -> str:
    cleaned = _ANSI_RE.sub("", raw)
    if "\r" in cleaned:
        cleaned = cleaned.split("\r")[-1]
    return cleaned.strip()


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _path_needs_home(path: str, windows: bool) -> bool:
    value = path.strip()
    return value == "~" or value.startswith("~/") or (
        windows and value.startswith("~\\")
    )


def _normalize_remote_path(path: str, platform: str, remote_home: str = "") -> str:
    value = path.strip()
    windows = platform == "windows"
    if not value:
        raise ValueError("DonkeyDrift 和 GymDonkeyCar 仓库路径不能为空。")
    if _path_needs_home(value, windows):
        if not remote_home.strip():
            raise ValueError("展开仓库路径前必须检测到远程用户主目录。")
        value = remote_home.strip() + value[1:]
    if windows:
        value = ntpath.normpath(value.replace("/", "\\"))
        drive, _ = ntpath.splitdrive(value)
        if not drive or not ntpath.isabs(value):
            raise ValueError(f"Windows 仓库路径必须是规范化绝对路径: {path}")
        return value
    value = posixpath.normpath(value)
    if not value.startswith("/"):
        raise ValueError(f"POSIX 仓库路径必须是规范化绝对路径: {path}")
    return value


def _powershell_command(script: str) -> str:
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return f"powershell -NoProfile -NonInteractive -EncodedCommand {encoded}"


def _posix_step(name: str, script: str) -> InstallStep:
    return InstallStep(name, f"zsh -lc {shlex.quote(script)}")


def _windows_step(name: str, script: str) -> InstallStep:
    command = _powershell_command(script)
    if len(command) <= 8191:
        return InstallStep(name, command)

    payload = base64.b64encode(gzip.compress(script.encode("utf-8"), mtime=0)).decode("ascii")
    bootstrap = f"""$ddGzip='{payload}'
$ddInput=New-Object System.IO.MemoryStream -ArgumentList (,[System.Convert]::FromBase64String($ddGzip))
$ddZip=New-Object System.IO.Compression.GzipStream($ddInput,[System.IO.Compression.CompressionMode]::Decompress)
$ddOutput=New-Object System.IO.MemoryStream
$ddZip.CopyTo($ddOutput)
$ddZip.Dispose()
$ddInput.Dispose()
Invoke-Expression ([System.Text.Encoding]::UTF8.GetString($ddOutput.ToArray()))"""
    command = _powershell_command(bootstrap)
    if len(command) > 8191:
        raise ValueError(f"Windows 步骤 {name} 压缩后仍超过 8191 字符，请缩短仓库路径。")
    return InstallStep(name, command)


def _mac_prelude(python_mirror: bool = False) -> str:
    lines = [
        "set -e",
        'export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"',
        f"export UV_DEFAULT_INDEX={shlex.quote(UV_INDEX)}",
    ]
    if python_mirror:
        lines.append(f"export UV_PYTHON_INSTALL_MIRROR={shlex.quote(UV_PYTHON_MIRROR)}")
    return "\n".join(lines)


def _windows_prelude(python_mirror: bool = False) -> str:
    lines = [
        "$ErrorActionPreference = 'Stop'",
        "Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force",
        '$env:Path = "$HOME\\.local\\bin;$HOME\\.cargo\\bin;$env:Path"',
        f"$env:UV_DEFAULT_INDEX = {_ps_quote(UV_INDEX)}",
    ]
    if python_mirror:
        lines.append(f"$env:UV_PYTHON_INSTALL_MIRROR = {_ps_quote(UV_PYTHON_MIRROR)}")
    return "\n".join(lines)


def _profile_update_script() -> str:
    return f"""import base64, gzip, locale, os, re, sys
profile = os.path.abspath(os.path.expanduser(sys.argv[1]))
block = gzip.decompress(base64.b64decode(os.environ['DD_HOOK_B64'])).decode('utf-8')
try:
    with open(profile, 'rb') as handle:
        original = handle.read()
except FileNotFoundError:
    original = None
if original is None:
    bom = b'\\xef\\xbb\\xbf' if os.environ.get('DD_HOOK_WINDOWS') == '1' else b''
    encoding = 'utf-8'
    text = ''
else:
    if original.startswith(b'\\xef\\xbb\\xbf'):
        bom, encoding = b'\\xef\\xbb\\xbf', 'utf-8'
    elif original.startswith(b'\\xff\\xfe'):
        bom, encoding = b'\\xff\\xfe', 'utf-16-le'
    elif original.startswith(b'\\xfe\\xff'):
        bom, encoding = b'\\xfe\\xff', 'utf-16-be'
    else:
        bom, encoding = b'', 'utf-8'
    raw = original[len(bom):]
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError:
        if bom:
            raise
        encoding = locale.getpreferredencoding(False)
        text = raw.decode(encoding)
newline = '\\r\\n' if '\\r\\n' in text else '\\n'
block = block.replace('\\r\\n', '\\n').replace('\\n', newline).rstrip('\\r\\n')
pattern = re.compile(r'(?ms)^' + re.escape({_HOOK_START!r}) + r'.*?^' + re.escape({_HOOK_END!r}) + r'(?:\\r\\n|\\n)?')
prefix = pattern.sub('', text)
if not prefix:
    updated = block + newline
else:
    if prefix.endswith(newline * 2):
        separator = ''
    elif prefix.endswith(newline):
        separator = newline
    else:
        separator = newline * 2
    updated = prefix + separator + block + newline
os.makedirs(os.path.dirname(profile), exist_ok=True)
temporary = profile + '.donkeydrift.tmp'
with open(temporary, 'wb') as handle:
    handle.write(bom + updated.encode(encoding))
os.replace(temporary, profile)
print('Hook updated: ' + profile)
"""


def _mac_hook(repo_path: str, gym_path: str) -> str:
    venv = f"{repo_path}/.venv"
    return f"""{_HOOK_START}
autoload -Uz add-zsh-hook
_donkeydrift_auto_venv() {{
  local venv_dir=""
  case "$PWD" in
    {shlex.quote(repo_path)}|{shlex.quote(repo_path)}/*|{shlex.quote(gym_path)}|{shlex.quote(gym_path)}/*) venv_dir={shlex.quote(venv)} ;;
  esac
  if [[ -n "$venv_dir" ]]; then
    [[ "$VIRTUAL_ENV" != "$venv_dir" ]] && source "$venv_dir/bin/activate"
  elif [[ -n "$VIRTUAL_ENV" && "$VIRTUAL_ENV" == {shlex.quote(venv)} ]]; then
    deactivate
  fi
}}
add-zsh-hook chpwd _donkeydrift_auto_venv
_donkeydrift_auto_venv
{_HOOK_END}"""


def _windows_hook(repo_path: str, gym_path: str) -> str:
    venv = f"{repo_path}\\.venv"
    activate = f"{venv}\\Scripts\\Activate.ps1"
    return f"""{_HOOK_START}
$global:DonkeyDriftRepoPath = {_ps_quote(repo_path)}
$global:DonkeyDriftGymPath = {_ps_quote(gym_path)}
$global:DonkeyDriftVenvPath = {_ps_quote(venv)}
function global:Update-DonkeyDriftVenv {{
  $repoPrefix = $global:DonkeyDriftRepoPath.TrimEnd('\\') + '\\'
  $gymPrefix = $global:DonkeyDriftGymPath.TrimEnd('\\') + '\\'
  $inside = $PWD.Path -eq $global:DonkeyDriftRepoPath -or
    $PWD.Path.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase) -or
    $PWD.Path -eq $global:DonkeyDriftGymPath -or
    $PWD.Path.StartsWith($gymPrefix, [StringComparison]::OrdinalIgnoreCase)
  if ($inside) {{
    if ($env:VIRTUAL_ENV -ne $global:DonkeyDriftVenvPath) {{
      $oldDisablePrompt = $env:VIRTUAL_ENV_DISABLE_PROMPT
      $env:VIRTUAL_ENV_DISABLE_PROMPT = '1'
      & {_ps_quote(activate)}
      if ($null -eq $oldDisablePrompt) {{
        Remove-Item Env:VIRTUAL_ENV_DISABLE_PROMPT -ErrorAction SilentlyContinue
      }} else {{
        $env:VIRTUAL_ENV_DISABLE_PROMPT = $oldDisablePrompt
      }}
    }}
  }} elseif ($env:VIRTUAL_ENV -eq $global:DonkeyDriftVenvPath) {{
    if (Get-Command deactivate -ErrorAction SilentlyContinue) {{ deactivate }}
  }}
}}
if (-not (Get-Variable DonkeyDriftOriginalPrompt -Scope Global -ErrorAction SilentlyContinue)) {{
  $global:DonkeyDriftOriginalPrompt = $function:prompt
}}
function global:prompt {{
  Update-DonkeyDriftVenv
  if ($global:DonkeyDriftOriginalPrompt) {{
    & $global:DonkeyDriftOriginalPrompt
  }} else {{
    "PS $($PWD.Path)> "
  }}
}}
Update-DonkeyDriftVenv
{_HOOK_END}"""


def _verification_script(platform: str) -> str:
    expected_tf = "2.15." if platform == "macos" else "2.19."
    require_gpu = platform == "macos"
    return f"""import os, sys
from importlib.metadata import PackageNotFoundError, distribution
import donkeycar, gym_donkeycar, gymnasium
import numpy as np
import tensorflow as tf
assert sys.version_info[:2] == (3, 11), sys.version
assert np.__version__ == '1.26.4', np.__version__
def source_root(module):
    return os.path.normcase(os.path.realpath(os.path.dirname(os.path.dirname(module.__file__))))
assert source_root(donkeycar) == os.path.normcase(os.path.realpath(sys.argv[1])), donkeycar.__file__
assert source_root(gym_donkeycar) == os.path.normcase(os.path.realpath(sys.argv[2])), gym_donkeycar.__file__
print('donkeydrifter distribution: ' + distribution('donkeydrifter').version)
print('gym_donkeycar distribution: ' + distribution('gym_donkeycar').version)
try:
    distribution('donkeycar')
except PackageNotFoundError:
    pass
else:
    raise RuntimeError('上游 donkeycar distribution 仍存在，拒绝继续。')
assert tf.__version__.startswith({expected_tf!r}), tf.__version__
devices = tf.config.list_physical_devices()
if {require_gpu!r}:
    assert any(device.device_type == 'GPU' for device in devices), devices
environments = [item for item in gymnasium.envs.registry if 'donkey' in item]
assert len(environments) == 11, environments
print('Python: ' + sys.version.replace('\\n', ' '))
print('TensorFlow: ' + tf.__version__)
print('numpy: ' + np.__version__)
print('GPU: ' + repr([str(device) for device in devices]))
print('donkeycar source: ' + donkeycar.__file__)
print('gym_donkeycar source: ' + gym_donkeycar.__file__)
print('Gym environments: ' + repr(environments))
"""


def _summary_script() -> str:
    return """import sys
import numpy as np
import tensorflow as tf
print('Python: ' + sys.version.replace('\\n', ' '))
print('TensorFlow: ' + tf.__version__)
print('numpy: ' + np.__version__)
print('GPU: ' + repr([str(device) for device in tf.config.list_physical_devices()]))
"""


def _is_python_download_timeout(output: str) -> bool:
    lowered = output.lower()
    return bool(re.search(r"timed?\s*out|timeout|超时", lowered)) and "python" in lowered or "download" in lowered and "timed out" in lowered


def _build_install_steps(platform: str, repo_path: str, gym_path: str,
                         python_mirror: bool = False,
                         remote_home: str = "") -> list[InstallStep]:
    if platform not in ("macos", "windows"):
        raise ValueError(f"不支持的平台: {platform}；仅支持 macOS Apple Silicon 和 Windows PowerShell。")
    repo_path = _normalize_remote_path(repo_path, platform, remote_home)
    gym_path = _normalize_remote_path(gym_path, platform, remote_home)

    windows = platform == "windows"
    extras = "pc,dev" if windows else "macos,dev"
    quote = _ps_quote if windows else shlex.quote
    venv = f"{repo_path}\\.venv" if windows else f"{repo_path}/.venv"
    venv_python = f"{venv}\\Scripts\\python.exe" if windows else f"{venv}/bin/python"
    donkey_cli = f"{venv}\\Scripts\\donkey.exe" if windows else f"{venv}/bin/donkey"
    repo_git = f"{repo_path}\\.git" if windows else f"{repo_path}/.git"
    gym_git = f"{gym_path}\\.git" if windows else f"{gym_path}/.git"
    editable_repo = f"{repo_path}[{extras}]"
    pin_args = " ".join(quote(value) for value in PINS)
    install_args = f"{quote(editable_repo)} -e {quote(gym_path)} {pin_args}"
    repair_args = f"{quote(editable_repo)} {pin_args}"
    prelude = _windows_prelude(python_mirror) if windows else _mac_prelude(python_mirror)
    make_step = _windows_step if windows else _posix_step
    native_check = "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }"
    steps = []

    if windows:
        tools = f"""{prelude}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {{ throw '未找到 git，请先安装 Git for Windows。' }}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {{
  Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
  $env:Path = "$HOME\\.local\\bin;$HOME\\.cargo\\bin;$env:Path"
}}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {{ throw 'uv 安装失败。' }}
& uv --version
{native_check}
& git --version
{native_check}
if (-not (Test-Path {_ps_quote(repo_git)})) {{ throw {_ps_quote(f'DonkeyDrift 仓库不存在或不是 Git 仓库: {repo_path}')} }}
Write-Output ('DD commit: ' + (& git -C {_ps_quote(repo_path)} rev-parse HEAD))
{native_check}
"""
        gym = f"""{prelude}
if (Test-Path {_ps_quote(gym_git)}) {{
  Write-Output '复用已有 GymDonkeyCar 仓库。'
}} elseif (Test-Path {_ps_quote(gym_path)}) {{
  throw 'Gym 路径已存在但不是 Git 仓库，未修改或删除该目录。'
}} else {{
  $parent = Split-Path -Parent {_ps_quote(gym_path)}
  New-Item -ItemType Directory -Force -Path $parent | Out-Null
  & git clone {GYM_REPOSITORY} {_ps_quote(gym_path)}
  {native_check}
}}
Write-Output ('Gym commit: ' + (& git -C {_ps_quote(gym_path)} rev-parse HEAD))
{native_check}
"""
        venv_step = f"""{prelude}
if (Test-Path {_ps_quote(venv)}) {{
  if (-not (Test-Path {_ps_quote(venv_python)})) {{ throw '已有 .venv 损坏或路径已搬家；未删除，请人工检查。' }}
  Write-Output '复用已有共享 .venv。'
}} else {{
  & uv venv --python 3.11 --prompt DonkeyDrift {_ps_quote(venv)}
  {native_check}
}}
& {_ps_quote(venv_python)} -c 'import sys; assert sys.version_info[:2] == (3, 11), sys.version'
{native_check}
"""
        install = f"""{prelude}
& uv pip install --python {_ps_quote(venv_python)} -e {install_args}
{native_check}
"""
        repair = f"""{prelude}
& uv pip show --python {_ps_quote(venv_python)} donkeycar 2>$null
if ($LASTEXITCODE -eq 0) {{
  Write-Output '发现上游 donkeycar，卸载并重装 donkeydrifter。'
  & uv pip uninstall --python {_ps_quote(venv_python)} donkeycar
  {native_check}
  & uv pip install --python {_ps_quote(venv_python)} -e {repair_args}
  {native_check}
}} else {{
  Write-Output '未发现上游 donkeycar，donkeydrifter 保持不变。'
}}
"""
        hook_block = _windows_hook(repo_path, gym_path)
        hook = f"""{prelude}
$env:DD_HOOK_B64='{base64.b64encode(gzip.compress(hook_block.encode(), mtime=0)).decode()}'
$env:DD_HOOK_WINDOWS='1'
& {_ps_quote(venv_python)} -c {_ps_quote(_profile_update_script())} $PROFILE
{native_check}
"""
        verify = f"""{prelude}
& uv pip check --python {_ps_quote(venv_python)}
{native_check}
& {_ps_quote(venv_python)} -c {_ps_quote(_verification_script(platform))} {_ps_quote(repo_path)} {_ps_quote(gym_path)}
{native_check}
$ddHelpEap = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
$help = & {_ps_quote(donkey_cli)} --help 2>&1
$ErrorActionPreference = $ddHelpEap
{native_check}
$help | Out-String | Write-Output
foreach ($command in @('createcar', 'train', 'web', 'drive', 'tui', 'installweb')) {{
  if (($help | Out-String) -notmatch $command) {{ throw "donkey CLI 缺少子命令: $command" }}
}}
Write-Output '安装验收通过。'
"""
        activation = f"""{prelude}
. $PROFILE
Set-Location -Path {_ps_quote(repo_path)}
prompt | Out-Null
if ($env:VIRTUAL_ENV -ne {_ps_quote(venv)}) {{ throw '进入 DonkeyDrift 后未激活共享 venv。' }}
Set-Location -Path {_ps_quote(gym_path)}
prompt | Out-Null
if ($env:VIRTUAL_ENV -ne {_ps_quote(venv)}) {{ throw '进入 GymDonkeyCar 后未激活共享 venv。' }}
Set-Location -Path (Join-Path {_ps_quote(gym_path)} 'gym_donkeycar')
prompt | Out-Null
if ($env:VIRTUAL_ENV -ne {_ps_quote(venv)}) {{ throw '进入 Gym 子目录后未保持共享 venv。' }}
Write-Output ('Hook activation: ' + $env:VIRTUAL_ENV)
Set-Location -Path $HOME
prompt | Out-Null
if ($env:VIRTUAL_ENV) {{ throw '离开仓库后未停用共享 venv。' }}
Write-Output 'Hook deactivation: passed'
"""
        summary = f"""{prelude}
Write-Output '=== DonkeyDrift installation summary ==='
$ddUvVersion = & uv --version
{native_check}
Write-Output ('uv: ' + $ddUvVersion)
Write-Output {_ps_quote(f'DD path: {repo_path}')}
$ddRepoCommit = & git -C {_ps_quote(repo_path)} rev-parse HEAD
{native_check}
Write-Output ('DD commit: ' + $ddRepoCommit)
Write-Output {_ps_quote(f'Gym path: {gym_path}')}
$ddGymCommit = & git -C {_ps_quote(gym_path)} rev-parse HEAD
{native_check}
Write-Output ('Gym commit: ' + $ddGymCommit)
Write-Output {_ps_quote(f'Venv: {venv}')}
& {_ps_quote(venv_python)} -c {_ps_quote(_summary_script())}
{native_check}
Write-Output 'Hook: current user $PROFILE (donkeydrift-auto-activate)'
Write-Output 'Acceptance: installation and automatic activation passed'
"""
    else:
        tools = f"""{prelude}
if ! command -v git >/dev/null 2>&1; then
  echo "错误：未找到 git，请先安装 Command Line Tools for Xcode。" >&2
  exit 1
fi
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
command -v uv >/dev/null 2>&1 || {{ echo "uv 安装失败。" >&2; exit 1; }}
uv --version
git --version
if [ ! -e {shlex.quote(repo_path + '/.git')} ]; then
  echo {shlex.quote(f'DonkeyDrift 仓库不存在或不是 Git 仓库: {repo_path}')} >&2
  exit 1
fi
dd_repo_commit="$(git -C {shlex.quote(repo_path)} rev-parse HEAD)"
echo "DD commit: $dd_repo_commit"
"""
        gym = f"""{prelude}
if [ -e {shlex.quote(gym_path + '/.git')} ]; then
  echo "复用已有 GymDonkeyCar 仓库。"
elif [ -e {shlex.quote(gym_path)} ]; then
  echo "Gym 路径已存在但不是 Git 仓库，未修改或删除该目录。" >&2
  exit 1
else
  mkdir -p {shlex.quote(posixpath.dirname(gym_path) or '.')}
  git clone {GYM_REPOSITORY} {shlex.quote(gym_path)}
fi
dd_gym_commit="$(git -C {shlex.quote(gym_path)} rev-parse HEAD)"
echo "Gym commit: $dd_gym_commit"
"""
        venv_step = f"""{prelude}
if [ -e {shlex.quote(venv)} ]; then
  if [ ! -x {shlex.quote(venv_python)} ]; then
    echo "已有 .venv 损坏或路径已搬家；未删除，请人工检查。" >&2
    exit 1
  fi
  echo "复用已有共享 .venv。"
else
  uv venv --python 3.11 --prompt DonkeyDrift {shlex.quote(venv)}
fi
{shlex.quote(venv_python)} -c 'import sys; assert sys.version_info[:2] == (3, 11), sys.version'
"""
        install = f"""{prelude}
uv pip install --python {shlex.quote(venv_python)} -e {install_args}
"""
        repair = f"""{prelude}
if uv pip show --python {shlex.quote(venv_python)} donkeycar >/dev/null 2>&1; then
  echo "发现上游 donkeycar，卸载并重装 donkeydrifter。"
  uv pip uninstall --python {shlex.quote(venv_python)} donkeycar
  uv pip install --python {shlex.quote(venv_python)} -e {repair_args}
else
  echo "未发现上游 donkeycar，donkeydrifter 保持不变。"
fi
"""
        hook_block = _mac_hook(repo_path, gym_path)
        hook = f"""{prelude}
export DD_HOOK_B64={base64.b64encode(gzip.compress(hook_block.encode(), mtime=0)).decode()}
{shlex.quote(venv_python)} -c {shlex.quote(_profile_update_script())} "$HOME/.zshrc"
"""
        verify = f"""{prelude}
uv pip check --python {shlex.quote(venv_python)}
{shlex.quote(venv_python)} -c {shlex.quote(_verification_script(platform))} {shlex.quote(repo_path)} {shlex.quote(gym_path)}
echo "donkey --help"
help_output="$({shlex.quote(donkey_cli)} --help 2>&1)"
echo "$help_output"
for command in createcar train web drive tui installweb; do
  echo "$help_output" | grep -q "$command" || {{ echo "donkey CLI 缺少子命令: $command" >&2; exit 1; }}
done
echo "安装验收通过。"
"""
        activation_inner = f"""cd {shlex.quote(repo_path)} && [[ "$VIRTUAL_ENV" == {shlex.quote(venv)} ]] || exit 1
cd {shlex.quote(gym_path)} && [[ "$VIRTUAL_ENV" == {shlex.quote(venv)} ]] || exit 1
cd {shlex.quote(gym_path + '/gym_donkeycar')} && [[ "$VIRTUAL_ENV" == {shlex.quote(venv)} ]] || exit 1
print -r -- "Hook activation: $VIRTUAL_ENV"
cd "$HOME"
[[ -z "${{VIRTUAL_ENV:-}}" ]] || exit 1
print -r -- 'Hook deactivation: passed'"""
        activation = f"""{prelude}
zsh -ic {shlex.quote(activation_inner)}
"""
        summary = f"""{prelude}
echo "=== DonkeyDrift installation summary ==="
dd_uv_version="$(uv --version)"
echo "uv: $dd_uv_version"
echo {shlex.quote(f'DD path: {repo_path}')}
dd_repo_commit="$(git -C {shlex.quote(repo_path)} rev-parse HEAD)"
echo "DD commit: $dd_repo_commit"
echo {shlex.quote(f'Gym path: {gym_path}')}
dd_gym_commit="$(git -C {shlex.quote(gym_path)} rev-parse HEAD)"
echo "Gym commit: $dd_gym_commit"
echo {shlex.quote(f'Venv: {venv}')}
{shlex.quote(venv_python)} -c {shlex.quote(_summary_script())}
echo "Hook: $HOME/.zshrc (donkeydrift-auto-activate)"
echo "Acceptance: installation and automatic activation passed"
"""

    for name, script in (
        ("prepare-tools", tools),
        ("prepare-gym", gym),
        ("prepare-venv", venv_step),
        ("install-dependencies", install),
        ("remove-upstream-donkeycar", repair),
        ("install-shell-hook", hook),
        ("verify-installation", verify),
        ("verify-shell-hook", activation),
        ("print-summary", summary),
    ):
        steps.append(make_step(name, script))
    return steps


def build_install_steps(platform: str, repo_path: str, gym_path: str,
                        remote_home: str = "") -> list[InstallStep]:
    return _build_install_steps(
        platform, repo_path, gym_path, remote_home=remote_home
    )
