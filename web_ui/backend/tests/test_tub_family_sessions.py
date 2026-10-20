import json
import os
import sys
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _make_tub(base_path: Path, record_count: int = 3) -> None:
    """Create a tub with the given number of live frames (mirrors test_tub_sessions)."""
    from donkeycar.parts.tub_v2 import Tub

    run = Tub(
        str(base_path),
        inputs=['cam/image_array', 'user/angle', 'user/throttle'],
        types=['image_array', 'float', 'float'],
    )
    for i in range(record_count):
        run.write_record({
            'user/angle': 0.1 * i,
            'user/throttle': 0.5,
        })
    run.close()


def _build_client():
    from routers import tub as tub_router

    app = FastAPI()
    app.include_router(tub_router.router, prefix="/api/tub")
    return TestClient(app)


class _FakeClock:
    """可控时钟：tub_v2.write_record 用 time.time() 打 _timestamp_ms，
    逐次 +1s 递增，保证跨 tub 的 start_time_ms 顺序确定。"""

    def __init__(self) -> None:
        self.now = time.time()

    def time(self) -> float:
        self.now += 1.0
        return self.now


def _use_fake_clock(monkeypatch) -> None:
    monkeypatch.setattr('donkeycar.parts.tub_v2.time', _FakeClock())


def _pin_session_id(monkeypatch, full_id: str = '26-10-20_0') -> None:
    """两个 tub 的首个会话天然会撞名（同一天都是 _0），钉死以免跨午夜 flake。"""
    monkeypatch.setattr(
        'donkeycar.parts.datastore_v2.Manifest.create_new_session_id',
        lambda self: (0, full_id),
    )


def test_family_sessions_from_child_tub_aggregates_siblings(tmp_path, monkeypatch):
    _use_fake_clock(monkeypatch)
    _make_tub(tmp_path / 'tub_a', record_count=2)
    _make_tub(tmp_path / 'tub_b', record_count=3)
    # 非 tub 目录与隐藏目录不应进入家族
    (tmp_path / 'plain_dir').mkdir()
    (tmp_path / '.hidden').mkdir()

    client = _build_client()
    response = client.get(
        '/api/tub/family_sessions', params={'tubPath': str(tmp_path / 'tub_a')}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload['status'] is True
    assert payload['family_root'] == str(tmp_path)
    sessions = payload['sessions']
    assert len(sessions) == 2
    by_tub = {s['tub_name']: s for s in sessions}
    assert set(by_tub) == {'tub_a', 'tub_b'}
    assert by_tub['tub_a']['tub_path'] == os.path.abspath(tmp_path / 'tub_a')
    assert by_tub['tub_b']['tub_path'] == os.path.abspath(tmp_path / 'tub_b')
    assert by_tub['tub_a']['record_count'] == 2
    assert by_tub['tub_b']['record_count'] == 3


def test_family_sessions_from_parent_dir_aggregates_child_tubs(tmp_path, monkeypatch):
    """path 本身不是 tub（无 manifest.json）时，家族 = 深度 ≤ 2 的子 tub。"""
    _use_fake_clock(monkeypatch)
    _make_tub(tmp_path / 'tub_1', record_count=2)
    _make_tub(tmp_path / 'data' / 'tub_2', record_count=3)

    client = _build_client()
    response = client.get('/api/tub/family_sessions', params={'tubPath': str(tmp_path)})

    assert response.status_code == 200
    payload = response.json()
    assert payload['family_root'] == str(tmp_path)
    by_tub = {s['tub_name']: s for s in payload['sessions']}
    assert set(by_tub) == {'tub_1', 'tub_2'}
    assert 'child_tubs' not in payload


def test_family_sessions_includes_parent_tub_when_parent_is_tub(tmp_path, monkeypatch):
    """path 是子 tub、父目录也是 tub 时：家族 = 自身 + 兄弟 + 父 tub。"""
    _use_fake_clock(monkeypatch)
    _make_tub(tmp_path, record_count=2)
    _make_tub(tmp_path / 'tub_child', record_count=3)
    _make_tub(tmp_path / 'tub_sibling', record_count=1)

    client = _build_client()
    response = client.get(
        '/api/tub/family_sessions', params={'tubPath': str(tmp_path / 'tub_child')}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload['family_root'] == str(tmp_path)
    by_tub = {s['tub_name']: s for s in payload['sessions']}
    assert set(by_tub) == {tmp_path.name, 'tub_child', 'tub_sibling'}


def test_family_sessions_same_session_id_in_two_tubs_both_listed(tmp_path, monkeypatch):
    """_session_id 跨 tub 撞名（如 tub_6/tub_7 都是 26-10-20_0）：复合键可区分。"""
    _use_fake_clock(monkeypatch)
    _pin_session_id(monkeypatch)
    _make_tub(tmp_path / 'tub_6_26-10-20', record_count=2)
    _make_tub(tmp_path / 'tub_7_26-10-20', record_count=3)

    client = _build_client()
    response = client.get(
        '/api/tub/family_sessions', params={'tubPath': str(tmp_path / 'tub_6_26-10-20')}
    )

    assert response.status_code == 200
    sessions = response.json()['sessions']
    assert len(sessions) == 2
    assert all(s['session_id'] == '26-10-20_0' for s in sessions)
    keys = {(s['tub_path'], s['session_id']) for s in sessions}
    assert keys == {
        (os.path.abspath(tmp_path / 'tub_6_26-10-20'), '26-10-20_0'),
        (os.path.abspath(tmp_path / 'tub_7_26-10-20'), '26-10-20_0'),
    }


def test_family_sessions_sorted_by_start_time_desc(tmp_path, monkeypatch):
    _use_fake_clock(monkeypatch)
    # 写库顺序 tub_old → tub_new，假时钟递增 → tub_new 的 start_time_ms 更晚
    _make_tub(tmp_path / 'tub_old', record_count=2)
    _make_tub(tmp_path / 'tub_new', record_count=2)

    client = _build_client()
    response = client.get(
        '/api/tub/family_sessions', params={'tubPath': str(tmp_path / 'tub_old')}
    )

    assert response.status_code == 200
    sessions = response.json()['sessions']
    assert [s['tub_name'] for s in sessions] == ['tub_new', 'tub_old']
    assert sessions[0]['start_time_ms'] >= sessions[1]['start_time_ms']


def test_family_sessions_empty_includes_child_tubs(tmp_path):
    """家族聚合为空（成员 tub 记录全软删）时，响应附带子 tub 引导（方案 A 兜底）。

    与 /tub/sessions 一致：child_tubs 扫描的是 path 的子目录（子 tub 不属于
    「path 是 tub」时的家族成员，但可作为引导目标列出）。

    用例放在 tmp_path 下一层沙盒目录里：path 是 tub 时家族会扫描其父目录的
    兄弟 tub，而 tmp_path 的父目录是 pytest 共享根目录，同轮其他用例的 tub
    会被当作兄弟混进来。
    """
    root = tmp_path / 'sandbox'
    root.mkdir()
    _make_tub(root, record_count=2)
    from donkeycar.parts.tub_v2 import Tub

    tub = Tub(str(root))
    try:
        tub.delete_records([0, 1])
    finally:
        tub.close()
    _make_tub(root / 'tub_7_26-10-20', record_count=4)

    client = _build_client()
    response = client.get('/api/tub/family_sessions', params={'tubPath': str(root)})

    assert response.status_code == 200
    payload = response.json()
    assert payload['sessions'] == []
    child_tubs = payload['child_tubs']
    assert len(child_tubs) == 1
    assert child_tubs[0]['name'] == 'tub_7_26-10-20'


def test_family_sessions_skips_corrupt_member(tmp_path, monkeypatch):
    """单个成员 tub 损坏（manifest 非法）仅告警跳过，其余成员不受影响。"""
    _use_fake_clock(monkeypatch)
    _make_tub(tmp_path / 'tub_good', record_count=2)
    (tmp_path / 'tub_broken').mkdir()
    (tmp_path / 'tub_broken' / 'manifest.json').write_text('not json')

    client = _build_client()
    response = client.get(
        '/api/tub/family_sessions', params={'tubPath': str(tmp_path / 'tub_good')}
    )

    assert response.status_code == 200
    sessions = response.json()['sessions']
    assert len(sessions) == 1
    assert sessions[0]['tub_name'] == 'tub_good'


def test_family_sessions_missing_path_returns_404(tmp_path):
    client = _build_client()
    response = client.get(
        '/api/tub/family_sessions', params={'tubPath': str(tmp_path / 'no_such_dir')}
    )
    assert response.status_code == 404


def test_family_sessions_response_has_no_duplicate_members(tmp_path, monkeypatch):
    """path 自身与父目录本身同时是 tub 时，path 不得重复计入家族。"""
    _use_fake_clock(monkeypatch)
    _make_tub(tmp_path, record_count=2)
    _make_tub(tmp_path / 'tub_child', record_count=2)

    client = _build_client()
    response = client.get(
        '/api/tub/family_sessions', params={'tubPath': str(tmp_path / 'tub_child')}
    )

    assert response.status_code == 200
    tub_paths = [s['tub_path'] for s in response.json()['sessions']]
    assert len(tub_paths) == len(set(tub_paths))
    # tub_child 只贡献一条会话（即使它同时以「自身」和「子 tub」身份出现）
    assert tub_paths.count(os.path.abspath(tmp_path / 'tub_child')) == 1
