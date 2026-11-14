#!/usr/bin/env bash
# 重生成 requirements-lock.txt（P0.2 依赖锁定，2026-10-12）。
#
# 输入: requirements.in（声明要锁定的 setup.cfg extras 组合）
# 输出: requirements-lock.txt（Linux x86_64 / Python 3.11 精确固定 + 哈希，
#       对应 CI 与 PC/服务端部署目标；pip-audit 直接审计该文件）
#
# 国内网络默认走清华 PyPI 镜像；CI/海外环境可设 LOCK_INDEX_URL 覆盖。
set -euo pipefail
cd "$(dirname "$0")/.."

INDEX_URL="${LOCK_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"

uv pip compile requirements.in \
    --python-version 3.11 \
    --python-platform linux \
    --no-emit-package donkeydrifter \
    --generate-hashes \
    --index-url "$INDEX_URL" \
    --output-file requirements-lock.txt

echo "requirements-lock.txt 已更新（$(grep -c '==' requirements-lock.txt) 个直接固定行）"
