import json

import numpy as np

from donkeycar.management.base import Evaluate


def test_evaluate_parse_args():
    args = Evaluate().parse_args(
        ['--tub', 'tub_a', 'tub_b', '--model', 'models/pilot',
         '--type', 'linear', '--out', 'results.json'])
    assert args.tub == ['tub_a', 'tub_b']
    assert args.model == 'models/pilot'
    assert args.type == 'linear'
    assert args.out == 'results.json'
    assert args.config == './config.py'


def test_evaluate_metrics_perfect_predictions():
    metrics = Evaluate()._metrics([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
    assert metrics['count'] == 3
    assert metrics['corr'] == 1.0
    assert metrics['mae'] == 0.0
    assert metrics['rmse'] == 0.0
    assert metrics['mean_err'] == 0.0


def test_evaluate_metrics_constant_true_yields_no_correlation():
    metrics = Evaluate()._metrics([5.0, 5.0, 5.0], [1.0, 2.0, 3.0])
    assert metrics['count'] == 3
    assert metrics['corr'] is None
    assert metrics['mae'] == 3.0
    assert np.isclose(metrics['rmse'], np.sqrt(29.0 / 3.0))
    assert metrics['mean_err'] == 3.0


def test_evaluate_run_without_model_writes_data_stats(monkeypatch, tmp_path):
    class FakeConfig:
        DEFAULT_MODEL_TYPE = 'linear'

    class FakeRecord:
        def __init__(self, angle, throttle):
            self.underlying = {'user/angle': angle, 'user/throttle': throttle}

    class FakeDataset:
        def __init__(self, config, tub_paths, seq_size):
            self._records = [
                FakeRecord(-0.5, 0.6), FakeRecord(0.0, 0.5), FakeRecord(0.5, 0.4)]
        def get_records(self):
            return self._records
        def close(self):
            pass

    monkeypatch.setattr('donkeycar.management.base.load_config',
                        lambda path: FakeConfig())
    monkeypatch.setattr('donkeycar.pipeline.types.TubDataset', FakeDataset)

    out_path = tmp_path / 'results.json'
    Evaluate().run(['--tub', 'tub_a', '--out', str(out_path)])

    data = json.loads(out_path.read_text(encoding='utf-8'))
    assert data['records'] == 3
    assert data['model'] is None
    assert 'angle_stats' in data
    assert 'throttle_stats' in data
    assert np.isclose(data['angle_stats']['mean'], 0.0)
    assert np.isclose(data['throttle_stats']['mean'], 0.5)
    # 角度 [-0.5, 0.0, 0.5]：直行 1/3、中间幅度 2/3、大转向 0；左 1/3、右 1/3。
    assert np.isclose(data['angle_stats']['abs_lt_0.05_ratio'], 1.0 / 3.0)
    assert np.isclose(data['angle_stats']['mid_ratio'], 2.0 / 3.0)
    assert np.isclose(data['angle_stats']['hard_ratio'], 0.0)
    assert np.isclose(data['angle_stats']['left_ratio'], 1.0 / 3.0)
    assert np.isclose(data['angle_stats']['right_ratio'], 1.0 / 3.0)
    # 该数据分布健康，不应产生告警
    assert 'warnings' not in data


def test_angle_health_warnings_healthy():
    stats = {
        'abs_lt_0.05_ratio': 0.30,
        'mid_ratio': 0.16,
        'hard_ratio': 0.54,
        'left_ratio': 0.37,
        'right_ratio': 0.62,
    }
    assert Evaluate()._angle_health_warnings(stats) == []


def test_angle_health_warnings_unhealthy():
    stats = {
        'abs_lt_0.05_ratio': 0.85,
        'mid_ratio': 0.032,
        'hard_ratio': 0.117,
        'left_ratio': 0.079,
        'right_ratio': 0.915,
    }
    warnings = Evaluate()._angle_health_warnings(stats)
    assert len(warnings) == 3
    assert any('mid_ratio' in w for w in warnings)
    assert any('左右转向样本严重失衡' in w for w in warnings)
    assert any('直行帧占比' in w for w in warnings)
