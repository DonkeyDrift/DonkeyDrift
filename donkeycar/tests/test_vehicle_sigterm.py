"""Vehicle 对 SIGTERM 的优雅收尾回归测试。

`donkey drive` 通过 SIGTERM 停止车端子进程；若不接管 SIGTERM，进程会立即
终止并跳过 Vehicle.start 的 finally，导致 stop() 末尾的 part 耗时表
（Part Profile Summary）不再输出。
"""
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_SIGTERM_SNIPPET = '''
import os
import signal
import threading
import time

import donkeycar as dk


class Part:
    def run(self):
        time.sleep(0.005)

    def shutdown(self):
        pass


v = dk.Vehicle()
v.add(Part())


def _terminate():
    time.sleep(0.3)
    os.kill(os.getpid(), signal.SIGTERM)


threading.Thread(target=_terminate, daemon=True).start()
v.start(rate_hz=50)
print("VEHICLE-START-RETURNED")
'''


def test_vehicle_sigterm_runs_stop_and_reports_profile():
    result = subprocess.run(
        [sys.executable, "-c", _SIGTERM_SNIPPET],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "VEHICLE-START-RETURNED" in result.stdout
    assert "Part Profile Summary" in result.stderr
    assert "| part" in result.stderr
