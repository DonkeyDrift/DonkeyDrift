#!/bin/bash
# 构建 aidlite 的「C-ABI 外壳 + ctypes 门面」并安装到目标 venv。
#
# 用途：当镜像只提供**别的 ABI** 的官方 aidlite 绑定（如本板 cp310），而工程要求
#       Python >=3.11 时，工程自己的解释器无法 import aidlite —— 本脚本给它补一个。
# 细节与前提：同目录 README.md。官方若已提供匹配 ABI 的绑定，本脚本会直接跳过。
#
# 用法: bash scripts/aidlite_cabi/rebuild.sh [venv 路径]   # 默认 <repo>/.venv
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
VENV="${1:-$REPO/.venv}"
HPP=/usr/local/include/aidlux/aidlite/aidlite.hpp
LIB=/usr/local/lib/libaidlite.so
SO="$HERE/libaidlite_cabi.so"

log() { printf '  %s\n' "$*"; }
die() { printf '  ✗ %s\n' "$*" >&2; exit 1; }

# 0) 目标解释器
[ -x "$VENV/bin/python" ] || die "找不到解释器 $VENV/bin/python（用法: bash scripts/aidlite_cabi/rebuild.sh [venv 路径]）"
PY="$VENV/bin/python"
PYVER="$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
log "目标解释器: $PY (Python $PYVER)"

# 1) 官方绑定已可用 → 什么都不做
if "$PY" -c 'import aidlite, sys; sys.exit(0 if str(aidlite.get_py_library_version()).startswith("Aidlux_Aidlite_P4L") else 1)' 2>/dev/null; then
    log "✓ 该解释器已能用官方 aidlite 绑定（$( "$PY" -c 'import aidlite; print(aidlite.get_py_library_version())' )）→ 无需自建"
    exit 0
fi
log "该解释器用不了官方绑定（ABI 不匹配）→ 构建自建绑定"

# 2) 依赖
[ -f "$HPP" ] || die "缺 $HPP —— 先装 SDK: sudo aid-pkg install aidlite-sdk"
[ -f "$LIB" ] || die "缺 $LIB —— 先装 SDK: sudo aid-pkg install aidlite-sdk"
"$PY" -c 'import numpy' 2>/dev/null || die "缺 numpy —— 门面用它做数组转换: $VENV/bin/pip install numpy（工程的 venv 通常已自带）"
command -v g++ >/dev/null 2>&1 || die "缺 g++ —— sudo apt-get install -y g++（本绑定是「共享库 + ctypes」，不需要 python3-dev）"

# 3) 编译
g++ -O2 -std=c++11 -fPIC -shared -I/usr/local/include \
    -o "$SO" "$HERE/aidlite_cabi.cpp" \
    -L/usr/local/lib -laidlite -Wl,-rpath,/usr/local/lib -pthread \
    || die "编译失败（若 aidlite.hpp 接口已变，按新头文件调整 aidlite_cabi.cpp）"
log "✓ 编译: $SO ($(stat -c%s "$SO") B)"

# 4) 安装进 venv
SP="$VENV/lib/python$PYVER/site-packages"
[ -d "$SP" ] || die "找不到 site-packages: $SP"
mkdir -p "$SP/aidlite"
cp "$HERE/aidlite/__init__.py" "$SP/aidlite/__init__.py"
cp "$SO" "$SP/aidlite/libaidlite_cabi.so"
log "✓ 安装到 $SP/aidlite/"

# 5) 自检
"$PY" - <<'PYEOF' || die "自检失败"
import sys, warnings
warnings.filterwarnings("ignore")
import aidlite
print("  python :", sys.version.split()[0])
print("  绑定   :", aidlite.get_py_library_version())
print("  C 库   :", aidlite.get_library_version())
PYEOF
log "✓ 完成 —— 该解释器现在可以 import aidlite（模型需 .aidem + qnn_model_info.json 同目录，且只能走 DSP）"
