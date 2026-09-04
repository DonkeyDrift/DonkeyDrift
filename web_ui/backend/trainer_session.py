"""mypc 断点续训会话存取。

每次 mypc 训练开始时，把远程工作目录、模型名、tub 与主机写进
<working_dir>/<config_file 主名>.session.json；「继续训练」据此找到上次
训练留下的最优权重检查点，加载权重后复用远程同一份数据接着练。
"""
import json
import os
import time
from typing import Optional


def _session_path(working_dir: str, config_file: str) -> str:
    stem = os.path.splitext(os.path.basename(config_file))[0]
    return os.path.join(working_dir, stem + ".session.json")


def save_session(working_dir: str, config_file: str, data: dict) -> None:
    """写入续训会话；data 字段：remote_work_dir / model_name / tub / host。

    写入失败不抛异常——会话丢失只是无法续训，绝不影响训练主流程。
    """
    payload = dict(data)
    payload["updated_at"] = time.time()
    try:
        with open(_session_path(working_dir, config_file), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_session(working_dir: str, config_file: str) -> Optional[dict]:
    """读取续训会话；文件不存在或解析失败返回 None。"""
    try:
        with open(_session_path(working_dir, config_file), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None
