"""Train --session-filter：按录制会话（_session_id）过滤训练数据。

覆盖三种形态：
1. 平坦列表 —— 对所有 tub 生效；
2. 按 tub 分组对象 —— (归一化 tub 路径, session_id) 命中才放行，不在映射中的
   tub 整体排除；
3. 容错 —— JSON 侧数字 id 与 record 的字符串 id 互相匹配；非法 JSON / 非法
   形态非零退出（SystemExit），绝不静默训练全量。
"""
import json
import os
from types import SimpleNamespace

import pytest

from donkeycar.config import Config
from donkeycar.management.base import Train
from donkeycar.parts.tub_v2 import Tub
from donkeycar.pipeline.types import TubDataset


def _make_tub_with_two_sessions(base_path, per_session=3):
    """同一个 tub 里写两段不同 _session_id 的记录。

    每次 Tub 实例化都会生成新 session id，重开一次再写即得第二段。
    """
    tub = Tub(base_path=base_path,
              inputs=['user/angle', 'user/throttle'], types=['float', 'float'])
    for i in range(per_session):
        tub.write_record({'user/angle': 0.1 * i, 'user/throttle': 0.5})
    tub.close()

    tub = Tub(base_path=base_path)
    for i in range(per_session):
        tub.write_record({'user/angle': -0.1 * i, 'user/throttle': 0.4})
    tub.close()


def _read_session_ids(base_path):
    tub = Tub(base_path, read_only=True)
    try:
        return {str(record.get('_session_id', '')) for record in tub}
    finally:
        tub.close()


def _records_for(tmp_path, tub_paths, filter_data):
    filter_path = tmp_path / 'session_filter.json'
    filter_path.write_text(json.dumps(filter_data), encoding='utf-8')
    cfg = Config()
    cfg.TRAIN_FILTER = Train()._load_session_filter(str(filter_path))
    dataset = TubDataset(cfg, list(tub_paths))
    try:
        return dataset.get_records()
    finally:
        dataset.close()


def test_flat_session_filter_keeps_only_selected_session(tmp_path):
    tub_dir = str(tmp_path / 'data')
    _make_tub_with_two_sessions(tub_dir, per_session=3)
    session_ids = _read_session_ids(tub_dir)
    assert len(session_ids) == 2

    keep = sorted(session_ids)[0]
    records = _records_for(tmp_path, [tub_dir], [keep])

    assert len(records) == 3
    assert {str(r.underlying['_session_id']) for r in records} == {keep}


def test_grouped_session_filter_matches_by_tub_path(tmp_path):
    tub_a = str(tmp_path / 'tub_a')
    tub_b = str(tmp_path / 'tub_b')
    _make_tub_with_two_sessions(tub_a, per_session=2)
    _make_tub_with_two_sessions(tub_b, per_session=2)

    keep_a = sorted(_read_session_ids(tub_a))[1]
    # tub_b 映射到空列表 = 整体排除；键同时验证 abspath/normpath 对齐
    records = _records_for(tmp_path, [tub_a, tub_b], {
        os.path.abspath(tub_a): [keep_a],
        os.path.join(tub_b, '..', 'tub_b'): [],
    })

    assert len(records) == 2
    assert {str(r.underlying['_session_id']) for r in records} == {keep_a}
    assert {os.path.normpath(os.path.abspath(r.base_path))
            for r in records} == {os.path.normpath(os.path.abspath(tub_a))}


def test_grouped_session_filter_excludes_unknown_tub(tmp_path):
    tub_dir = str(tmp_path / 'data')
    _make_tub_with_two_sessions(tub_dir, per_session=2)
    keep = sorted(_read_session_ids(tub_dir))[0]

    # 映射里的 tub 未参与本次加载：所有 record 都应被排除
    records = _records_for(tmp_path, [tub_dir], {str(tmp_path / 'other'): [keep]})
    assert records == []


def test_session_filter_tolerates_numeric_ids(tmp_path):
    filter_path = tmp_path / 'session_filter.json'
    filter_path.write_text(json.dumps([123]), encoding='utf-8')
    record = SimpleNamespace(underlying={'_session_id': '123'},
                             base_path='/tmp/whatever')
    record_other = SimpleNamespace(underlying={'_session_id': '124'},
                                   base_path='/tmp/whatever')

    flat = Train()._load_session_filter(str(filter_path))
    assert flat(record) is True
    assert flat(record_other) is False

    grouped_path = tmp_path / 'grouped.json'
    grouped_path.write_text(json.dumps({'/tmp/whatever': [123]}), encoding='utf-8')
    grouped = Train()._load_session_filter(str(grouped_path))
    assert grouped(record) is True
    assert grouped(SimpleNamespace(underlying={'_session_id': '123'},
                                   base_path='/tmp/other')) is False


def test_session_filter_missing_file_exits_nonzero(tmp_path):
    with pytest.raises(SystemExit):
        Train()._load_session_filter(str(tmp_path / 'nope.json'))


def test_session_filter_invalid_json_exits_nonzero(tmp_path):
    bad = tmp_path / 'bad.json'
    bad.write_text('{oops', encoding='utf-8')
    with pytest.raises(SystemExit):
        Train()._load_session_filter(str(bad))


def test_session_filter_bad_shape_exits_nonzero(tmp_path):
    bad = tmp_path / 'bad.json'
    bad.write_text('"just a string"', encoding='utf-8')
    with pytest.raises(SystemExit):
        Train()._load_session_filter(str(bad))

    bad2 = tmp_path / 'bad2.json'
    bad2.write_text(json.dumps({'/tmp/tub': 'not-a-list'}), encoding='utf-8')
    with pytest.raises(SystemExit):
        Train()._load_session_filter(str(bad2))
