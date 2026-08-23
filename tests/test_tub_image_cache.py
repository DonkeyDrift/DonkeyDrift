# -*- coding: utf-8 -*-
"""issue #128：Tub 图像接口的 LRU 缓存与 ETag/304 协商测试。

后端 /api/tub/image 原先每次请求都从磁盘读原始 JPEG 并以 FileResponse
返回，播放器 60fps 逐帧取图时磁盘读 + 无浏览器缓存协商会击穿前端预取
窗口，是 Tub Navigator 播放卡顿的后端成因。本测试验证：

1. 命中缓存时不再读磁盘（mtime/size 校验的 LRU 字节缓存）；
2. 响应带 ETag，If-None-Match 匹配时返回 304；
3. 响应带 Cache-Control，让浏览器 disk cache 参与重复播放；
4. 缓存总量超过预算时按 LRU 淘汰最旧条目。
"""
import builtins
import sys
from pathlib import Path

import pytest
from starlette.requests import Request

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "web_ui" / "backend"))

from routers import tub  # noqa: E402


def _make_tub(tmp_path: Path, name: str = "tub") -> Path:
    tub_dir = tmp_path / name
    (tub_dir / "images").mkdir(parents=True)
    (tub_dir / "manifest.json").write_text("{}", encoding="utf-8")
    return tub_dir


def _get_image(**kwargs):
    # get_image 已改为同步路由（线程池执行），直接调用即可
    return tub.get_image(**kwargs)


def _make_request(headers: dict) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    scope = {"type": "http", "method": "GET", "path": "/", "headers": raw}
    return Request(scope)


def test_image_response_has_etag_and_cache_control(tmp_path):
    tub_dir = _make_tub(tmp_path)
    payload = b"\xff\xd8fake-jpeg-bytes"
    (tub_dir / "images" / "1_cam_image_array_.jpg").write_bytes(payload)

    resp = _get_image(path="1_cam_image_array_.jpg", tubPath=str(tub_dir), request=_make_request({}))

    assert resp.status_code == 200
    assert resp.body == payload
    assert resp.media_type == "image/jpeg"
    assert resp.headers["etag"]
    assert "max-age" in resp.headers["cache-control"]


def test_second_hit_served_from_memory_cache(tmp_path, monkeypatch):
    tub_dir = _make_tub(tmp_path)
    img = tub_dir / "images" / "1_cam_image_array_.jpg"
    img.write_bytes(b"\xff\xd8fake-jpeg-bytes")

    _get_image(path="1_cam_image_array_.jpg", tubPath=str(tub_dir), request=_make_request({}))

    # 后续命中不应再打开文件：open 一旦被调用即失败
    real_open = open

    def guarded_open(file, *args, **kwargs):
        if str(file).endswith(".jpg"):
            raise AssertionError("cache hit must not touch the disk")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)

    resp = _get_image(path="1_cam_image_array_.jpg", tubPath=str(tub_dir), request=_make_request({}))
    assert resp.status_code == 200
    assert resp.body == b"\xff\xd8fake-jpeg-bytes"


def test_if_none_match_returns_304(tmp_path):
    tub_dir = _make_tub(tmp_path)
    (tub_dir / "images" / "1_cam_image_array_.jpg").write_bytes(b"\xff\xd8fake-jpeg-bytes")

    first = _get_image(path="1_cam_image_array_.jpg", tubPath=str(tub_dir), request=_make_request({}))
    etag = first.headers["etag"]

    second = _get_image(path="1_cam_image_array_.jpg", tubPath=str(tub_dir), request=_make_request({"if-none-match": etag}))
    assert second.status_code == 304
    assert second.headers["etag"] == etag


def test_changed_file_invalidates_cache_entry(tmp_path):
    tub_dir = _make_tub(tmp_path)
    img = tub_dir / "images" / "1_cam_image_array_.jpg"
    img.write_bytes(b"\xff\xd8old")

    _get_image(path="1_cam_image_array_.jpg", tubPath=str(tub_dir), request=_make_request({}))

    img.write_bytes(b"\xff\xd8new")
    # 显式推进 mtime，避免同一纳秒内写入导致缓存键未变
    import os
    st = os.stat(img)
    os.utime(img, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))

    resp = _get_image(path="1_cam_image_array_.jpg", tubPath=str(tub_dir), request=_make_request({}))
    assert resp.body == b"\xff\xd8new"


def test_cache_evicts_lru_when_over_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(tub, "IMAGE_CACHE_MAX_BYTES", 16)
    tub_dir = _make_tub(tmp_path)
    for i in range(3):
        (tub_dir / "images" / f"{i}_cam_image_array_.jpg").write_bytes(
            b"\xff\xd8" + bytes([48 + i]) * 8)

    for i in range(3):
        _get_image(path=f"{i}_cam_image_array_.jpg", tubPath=str(tub_dir), request=_make_request({}))

    # 预算 16 字节、每条约 10 字节：最多留 2 条，最旧的 0 号应被淘汰
    assert str(tub_dir / "images" / "0_cam_image_array_.jpg") not in tub._image_cache
    assert len(tub._image_cache) <= 2
    assert tub._image_cache_bytes <= 16
