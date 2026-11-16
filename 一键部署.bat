@echo off
chcp 65001 >nul
setlocal
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo 未找到 python，请先安装 Python 3 并加入 PATH。
  exit /b 1
)
python scripts\one_click_deploy.py %*
