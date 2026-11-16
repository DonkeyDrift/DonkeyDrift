#!/bin/zsh
set -euo pipefail
REPO_DIR="${0:A:h}"
if ! command -v python3 >/dev/null 2>&1; then
  echo "未找到 python3。请先安装 Xcode Command Line Tools：xcode-select --install" >&2
  exit 1
fi
exec python3 "$REPO_DIR/scripts/one_click_deploy.py" "$@"
