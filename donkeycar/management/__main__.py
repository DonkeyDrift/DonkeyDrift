"""`python -m donkeycar.management ...` —— 与 `donkey` 控制台命令等价的模块入口。

供 web 后端以 [sys.executable, '-m', 'donkeycar.management', 'train', ...]
拉起训练子进程：继承后端自身的解释器（3.12 NPU 环境下自动走 torch 训练），
不依赖 PATH 里恰好有哪个 venv 的 donkey。
"""
from donkeycar.management.base import execute_from_command_line

execute_from_command_line()
