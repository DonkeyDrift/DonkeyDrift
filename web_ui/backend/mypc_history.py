"""
Known-hosts history for 'This Computer' (mypc) training.

Remembers the computers that were successfully probed or used to start a
mypc training job, so the Trainer page can pre-fill the most recently used
connection. The history file (mypc_known_hosts.json) lives next to
train_my_pc.conf — the same directory get_trainer_config() resolves the
conf file to (os.path.abspath of the relative config filename, i.e. the
backend working directory).

安全约束：历史文件只存连接元信息（host / user / python_path /
remote_dir_base / last_used_at），绝不存密码——即使旧版本文件里残留
password 字段，加载时也直接丢弃，重写文件时彻底清掉。

All I/O is best-effort: any read/write error is swallowed (empty list /
no-op) so history bookkeeping can never break probing or training.
"""
import json
import os
import time
from typing import List

# Keep at most this many remembered computers; oldest are dropped first.
MAX_KNOWN_HOSTS = 10


def _history_path() -> str:
    """Absolute path of mypc_known_hosts.json, next to train_my_pc.conf."""
    conf_dir = os.path.dirname(os.path.abspath("train_my_pc.conf"))
    return os.path.join(conf_dir, "mypc_known_hosts.json")


def load_known_hosts() -> List[dict]:
    """Read the history file and return entries sorted by last_used_at desc.

    Each entry is {host, user, python_path, remote_dir_base, last_used_at}.
    Any ``password`` field left over from an older file format is dropped
    here — passwords are never returned to callers.
    Never raises — returns [] on any error or if the file does not exist.
    """
    try:
        path = _history_path()
        if not os.path.isfile(path):
            return []
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        entries = []
        for item in data:
            if not isinstance(item, dict) or not item.get("host"):
                continue
            entries.append({
                "host": str(item.get("host") or ""),
                "user": str(item.get("user") or ""),
                "python_path": str(item.get("python_path") or ""),
                "remote_dir_base": str(item.get("remote_dir_base") or ""),
                "last_used_at": float(item.get("last_used_at") or 0),
            })
        entries.sort(key=lambda e: e["last_used_at"], reverse=True)
        return entries
    except Exception:
        return []


def save_known_host(host: str, user: str, python_path: str = "",
                    remote_dir_base: str = "") -> None:
    """Upsert one computer into the history, keyed by host.

    last_used_at is set to now; empty python_path / remote_dir_base keep the
    previously stored values. At most MAX_KNOWN_HOSTS entries are kept
    (oldest dropped). The write is atomic: a temp file is written first,
    then os.replace()ed over the history file. Never raises.

    密码不入库：本函数没有 password 参数，写出的 JSON 永远不含密码。
    """
    tmp_path = ""
    try:
        if not host:
            return
        old_entries = load_known_hosts()
        old = next((e for e in old_entries if e["host"] == host), None)
        if not python_path:
            python_path = old["python_path"] if old else ""
        if not remote_dir_base:
            remote_dir_base = old["remote_dir_base"] if old else ""
        entries = [e for e in old_entries if e["host"] != host]
        entries.append({
            "host": host,
            "user": user,
            "python_path": python_path,
            "remote_dir_base": remote_dir_base,
            "last_used_at": time.time(),
        })
        entries.sort(key=lambda e: e["last_used_at"], reverse=True)
        entries = entries[:MAX_KNOWN_HOSTS]

        path = _history_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = f"{path}.{os.getpid()}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
