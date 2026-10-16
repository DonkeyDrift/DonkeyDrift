"""TubWriter 异步写线程：主循环零阻塞、顺序保持、满队丢旧、close 排空。

同步写会把录制时毫秒级的磁盘抖动（图像编码+catalog 落盘）直接灌进车辆
主循环，任一轮超时即掉帧。异步契约：
- run() 只入队立即返回，磁盘写入由后台线程串行执行
- new_tub 与记录共用同一队列，先后顺序天然保持（旧记录进旧 tub）
- 队列满丢最旧保最新，close/shutdown 排空队列再关闭
"""
import threading
import time

import pytest

from donkeycar.parts.tub_v2 import TubWriter

INPUTS = ['cam/image_array', 'user/angle', 'user/throttle', 'user/mode']
TYPES = ['image_array', 'float', 'float', 'str']


def _args(angle=0.0, tag=''):
    # run(*inputs) 按位置收参；image 传 None 时 write_record 会跳过该字段
    return (None, angle, 0.0, f'user{tag}')


def _wait_until(predicate, timeout=5.0, interval=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_async_run_returns_immediately_and_persists_all_records(tmp_path):
    tw = TubWriter(str(tmp_path / 'tub'), inputs=INPUTS, types=TYPES,
                   async_write=True)

    t0 = time.perf_counter()
    for i in range(20):
        idx = tw.run(*_args(angle=i * 0.01))
        assert isinstance(idx, int)
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.5, f"20 次入队不应被磁盘写入阻塞，实际 {elapsed:.3f}s"

    tw.close()
    assert tw.tub.manifest.current_index == 20, "close 应排空队列，20 条全部落盘"


def test_new_tub_keeps_queue_order(tmp_path):
    """换 tub 命令与记录同队列串行：旧记录必须落进旧 tub，新记录进新 tub。"""
    old_path, new_path = tmp_path / 'old', tmp_path / 'new'
    tw = TubWriter(str(old_path), inputs=INPUTS, types=TYPES, async_write=True)

    for i in range(3):
        tw.run(*_args(angle=i))
    tw.new_tub(str(new_path))
    for i in range(2):
        tw.run(*_args(angle=10 + i))
    tw.close()

    assert (old_path / 'manifest.json').exists(), "旧 tub 应保留换 tub 前的记录"
    assert (new_path / 'manifest.json').exists(), "换 tub 后应在新 tub 继续记录"


def test_queue_full_drops_oldest_without_blocking(tmp_path):
    """队列满时丢最旧保最新，run() 永不被磁盘写入阻塞。"""
    tw = TubWriter(str(tmp_path / 'tub'), inputs=INPUTS, types=TYPES,
                   async_write=True, queue_size=2)

    written = []
    gate = threading.Event()
    started = threading.Event()
    first_call = [True]

    def slow_write_record(record):
        if first_call[0]:
            first_call[0] = False
            started.set()
            gate.wait(timeout=5.0)  # 卡住第一条写入，制造队列积压
        written.append(record['user/mode'])

    tw.tub.write_record = slow_write_record

    # 先让 writer 确实取走第一条并阻塞，消除线程调度竞态
    tw.run(*_args(tag='0'))
    assert started.wait(timeout=2.0), "writer 线程应已取走第一条记录并阻塞"

    latency = []
    for i in range(1, 6):
        t0 = time.perf_counter()
        tw.run(*_args(tag=str(i)))
        latency.append(time.perf_counter() - t0)

    assert max(latency) < 0.1, "入队绝不能被慢速磁盘写入阻塞"
    assert tw._dropped > 0, "积压超限后应丢弃最旧记录并计数"

    gate.set()
    tw.close()
    # user0 被 writer 持有写完；user1~3 在队满时按最旧优先被丢弃
    assert written == ['user0', 'user4', 'user5'], \
        f"应丢弃队列积压中最旧的 user1~3，实际落盘: {written}"


def test_sync_mode_unchanged(tmp_path):
    """async_write=False 保持同步语义：run 返回即已落盘（兼容既有调用方）。"""
    tw = TubWriter(str(tmp_path / 'tub'), inputs=INPUTS, types=TYPES,
                   async_write=False)
    assert tw._thread is None

    idx = tw.run(*_args())
    assert idx == 1, "同步模式 run 返回即已写入"
    assert tw.num_records() == 1
    tw.close()


def test_shutdown_flushes_pending_records(tmp_path):
    """Vehicle.stop 走 shutdown()：排队中的记录也必须全部落盘。"""
    tw = TubWriter(str(tmp_path / 'tub'), inputs=INPUTS, types=TYPES,
                   async_write=True)
    for i in range(10):
        tw.run(*_args(angle=i))
    tw.shutdown()
    assert tw.tub.manifest.current_index == 10
    assert tw._thread is None, "shutdown 后 writer 线程应退出"
