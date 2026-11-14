#!/usr/bin/env python3
"""TubRecord 图像缓存的内存与速度基准（2026-10 OOM 修复配套）。

三个子命令：

  gen    生成合成 tub（渐变+噪声内容，jpg 尺寸接近真实行车数据）
  epoch  以训练同款访问模式（train_test_split 打乱后顺序遍历，每帧
         record.image()）跑若干个 epoch，逐 epoch 报告 RSS 曲线与耗时
  decode 量化 NOCACHE 的每帧磁盘读取+解码开销，对照缓存全命中的开销

本脚本在「有界缓存改动前后」均可运行：改动前的代码不认识
CACHE_MAX_BYTES 键，ARRAY 策略即无界全量驻留（即事故形态）；
改动后的代码用该键作为全局 LRU 字节预算。cache-stats 一行会
自动标注当前 build 是否带有有界缓存。

用法示例：
  python donkeycar/benchmarks/image_cache_bench.py gen --path /tmp/bench/tub3k \
      --count 3000 --width 320 --height 240
  python donkeycar/benchmarks/image_cache_bench.py epoch --tub /tmp/bench/tub3k \
      --policy ARRAY --max-bytes 268435456 --epochs 3
  python donkeycar/benchmarks/image_cache_bench.py decode --tub /tmp/bench/tub3k
"""
import argparse
import json
import os
import resource
import sys
import time


def vm_rss_mb() -> float:
    """当前 RSS（MB），读 /proc 避免 psutil 依赖。"""
    try:
        with open('/proc/self/status') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    return int(line.split()[1]) / 1024.0
    except OSError:
        pass
    return -1.0


def peak_rss_mb() -> float:
    """进程生命周期峰值 RSS（MB）；Linux 上 ru_maxrss 单位是 kB。"""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def make_config(policy: str, max_bytes: int, width: int, height: int):
    from donkeycar.config import Config
    cfg = Config()
    cfg.IMAGE_W = width
    cfg.IMAGE_H = height
    cfg.IMAGE_DEPTH = 3
    cfg.CACHE_POLICY = policy
    # 改动前的 build 不读取该键（getattr 也不存在），ARRAY 即无界驻留
    cfg.CACHE_MAX_BYTES = max_bytes
    return cfg


def cache_stats_line() -> str:
    try:
        from donkeycar.pipeline.image_cache import get_global_image_cache
        c = get_global_image_cache()
        s = c.stats()
        return f'bounded-cache=PRESENT {json.dumps(s, sort_keys=True)}'
    except ImportError:
        return 'bounded-cache=ABSENT (pre-patch build: ARRAY is unbounded)'


def gen_tub(path: str, count: int, width: int, height: int, seed: int) -> None:
    import numpy as np
    from donkeycar.parts.tub_v2 import Tub

    rng = np.random.default_rng(seed)
    tub = Tub(path, inputs=['cam/image_array', 'user/angle', 'user/throttle',
                            'user/mode'],
              types=['image_array', 'float', 'float', 'str'])
    xs = np.arange(width, dtype=np.float32) / width
    t0 = time.perf_counter()
    for i in range(count):
        phase = ((i * 7) % count) / count
        grad = (np.sin(xs * 6.28 * (1.0 + phase)) * 0.5 + 0.5) * 255.0
        frame = np.stack([np.tile(grad, (height, 1)),
                          np.tile(np.roll(grad, width // 4), (height, 1)),
                          np.tile(np.roll(grad, width // 2), (height, 1))],
                         axis=-1)
        frame = np.clip(frame + rng.normal(0.0, 6.0, frame.shape), 0, 255)
        arr = frame.astype(np.uint8)
        tub.write_record({'cam/image_array': arr,
                          'user/angle': float(np.sin(phase * 6.28) * 0.9),
                          'user/throttle': 0.4 + 0.2 * phase,
                          'user/mode': 'user'})
        if (i + 1) % 2000 == 0:
            dt = time.perf_counter() - t0
            print(f'  generated {i + 1}/{count} frames ({dt:.0f}s)',
                  flush=True)
    tub.close()
    print(f'tub written: {path} ({count} frames, {width}x{height}, '
          f'{time.perf_counter() - t0:.0f}s)')


def run_epochs(args) -> None:
    from donkeycar.pipeline.types import TubDataset
    from donkeycar.utils import train_test_split

    cfg = make_config(args.policy, args.max_bytes, args.width, args.height)
    ds = TubDataset(cfg, [args.tub])
    records = ds.get_records()
    # 与 training.train() 相同的切分：打乱一次、顺序固定，repeat() 每 epoch 同序
    train_records, _ = train_test_split(records, shuffle=True, test_size=0.2)
    print(f'records={len(records)} train_records={len(train_records)} '
          f'policy={args.policy} max_bytes={args.max_bytes} '
          f'image={args.width}x{args.height} '
          f'({args.width * args.height * 3} bytes/frame raw)')
    print(cache_stats_line())

    rss_base = vm_rss_mb()
    for epoch in range(1, args.epochs + 1):
        rss_start = vm_rss_mb()
        rss_max = rss_start
        t0 = time.perf_counter()
        n = 0
        for rec in train_records:
            _img = rec.image()  # 训练首次访问同款路径：加载并（按策略）缓存
            n += 1
            if n % 256 == 0:
                rss_max = max(rss_max, vm_rss_mb())
        rss_max = max(rss_max, vm_rss_mb())
        dt = time.perf_counter() - t0
        print(json.dumps({
            'epoch': epoch,
            'frames': n,
            'seconds': round(dt, 2),
            'ms_per_frame': round(dt * 1000.0 / n, 3),
            'rss_start_mb': round(rss_start, 1),
            'rss_end_mb': round(vm_rss_mb(), 1),
            'rss_max_in_epoch_mb': round(rss_max, 1),
            'rss_growth_vs_base_mb': round(vm_rss_mb() - rss_base, 1),
            'proc_peak_rss_mb': round(peak_rss_mb(), 1),
            'cache': cache_stats_line(),
        }, ensure_ascii=False), flush=True)


def run_decode(args) -> None:
    from donkeycar.pipeline.types import TubDataset

    n_frames = args.frames
    results = {}
    for policy, max_bytes, label in (
            ('NOCACHE', 0, 'nocache_disk_decode'),
            ('ARRAY', 1 << 40, 'array_all_hit'),
    ):
        cfg = make_config(policy, max_bytes, args.width, args.height)
        ds = TubDataset(cfg, [args.tub])
        records = ds.get_records()[:n_frames]
        # 预热：ARRAY 先遍历一遍填满缓存，保证第二轮全命中
        for rec in records:
            rec.image()
        t0 = time.perf_counter()
        for rec in records:
            rec.image()
        dt = time.perf_counter() - t0
        results[label] = round(dt * 1000.0 / n_frames, 3)
        print(json.dumps({
            'mode': label,
            'frames': n_frames,
            'ms_per_frame': results[label],
            'ms_per_batch_128': round(results[label] * 128, 1),
            'cache': cache_stats_line(),
        }, ensure_ascii=False), flush=True)
    extra = round(results['nocache_disk_decode'] - results['array_all_hit'], 3)
    print(json.dumps({
        'mode': 'decode_overhead_nocache_vs_hit',
        'ms_per_frame': extra,
        'seconds_per_20k_epoch': round(extra * 20000 / 1000.0, 1),
    }, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='cmd', required=True)

    p_gen = sub.add_parser('gen', help='generate synthetic tub')
    p_gen.add_argument('--path', required=True)
    p_gen.add_argument('--count', type=int, default=3000)
    p_gen.add_argument('--width', type=int, default=320)
    p_gen.add_argument('--height', type=int, default=240)
    p_gen.add_argument('--seed', type=int, default=42)

    p_ep = sub.add_parser('epoch', help='traverse epochs like training')
    p_ep.add_argument('--tub', required=True)
    p_ep.add_argument('--policy', default='ARRAY',
                      choices=['NOCACHE', 'ARRAY', 'BINARY'])
    p_ep.add_argument('--max-bytes', type=int, default=256 * 1024 * 1024,
                      help='CACHE_MAX_BYTES (ignored by pre-patch build)')
    p_ep.add_argument('--epochs', type=int, default=1)
    p_ep.add_argument('--width', type=int, default=320)
    p_ep.add_argument('--height', type=int, default=240)

    p_dec = sub.add_parser('decode', help='per-frame decode cost')
    p_dec.add_argument('--tub', required=True)
    p_dec.add_argument('--frames', type=int, default=300)
    p_dec.add_argument('--width', type=int, default=320)
    p_dec.add_argument('--height', type=int, default=240)

    args = parser.parse_args()
    if args.cmd == 'gen':
        gen_tub(args.path, args.count, args.width, args.height, args.seed)
    elif args.cmd == 'epoch':
        run_epochs(args)
    elif args.cmd == 'decode':
        run_decode(args)


if __name__ == '__main__':
    main()
