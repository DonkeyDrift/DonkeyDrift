# -*- coding: utf-8 -*-
"""launcher server.py 硬编码本机绝对路径的回归栅栏。

本仓库是 GitHub 公开仓库：源码（含 MENU_HTML 内嵌前端 JS）里硬编码
``/home/<用户名>/...`` 这类真实本机绝对路径，入库即泄露。launcher 的
dsh / kimi-code-web 启动端点缺省 cwd 与内嵌前端曾硬编码此类路径
（ZCode 入口 PR #359 收尾时登记的待单修项），已改为
``str(Path.home() / "projects")`` 动态推导；本测试逐行扫描 server.py，
除明确保留的 mycar 已知路径（``_find_mycar_project`` 的
``projects/mycar`` 搜索路径，属另一问题、不在该修复范围）外，
不允许任何行再出现 ``/home/<用户>/`` 形态的本机路径。
"""

import re
from pathlib import Path

from donkeycar.launcher import server as launcher_server

# /home/<用户>/ 形态的本机用户目录绝对路径
_LOCAL_HOME_RE = re.compile(r"/home/[^/]+/")


def test_server_py_has_no_hardcoded_local_absolute_paths():
    server_py = Path(launcher_server.__file__)
    offenders = []
    for lineno, line in enumerate(
            server_py.read_text(encoding="utf-8").splitlines(), 1):
        if not _LOCAL_HOME_RE.search(line):
            continue
        # 明确保留：_find_mycar_project 的 mycar 已知搜索路径（另一问题）
        if "projects/mycar" in line:
            continue
        offenders.append(f"{lineno}: {line.strip()}")
    assert not offenders, (
        "server.py 残留硬编码本机绝对路径（公开仓库入库即泄露）：\n"
        + "\n".join(offenders))
