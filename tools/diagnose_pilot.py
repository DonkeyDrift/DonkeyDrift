#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""drive 全自动 pilot 恒定输出问题的离线诊断脚本。

背景：同一 .tflite 模型在 Pilot Arena（tub 图像）推理正常，但车端 drive
全自动时 pilot 输出近似常数。静态排查已确认模型输入形状、resize 口径、
解释器环境（车端与后端同 venv）一致，本脚本用四组实验区分剩余根因：

  Test A  对照组：tub 图像 + arena 式预处理（PIL→RGB→cv2.resize 拉伸）
           直接 pilot.run()。预期输出随标签变化、MAE 小。
  Test B  同批图像走 PilotHolder.run()（letterbox 适配路径），与 A 对比
           确认车端预处理无差异。
  Test C  实时相机（pygame Webcam，与车端同款）：统计帧新鲜度（间隔/
           内容哈希）与输出变化。需独占相机，运行前先停车端进程；
           期间手持小车沿赛道移动效果最佳（无人配合时至少能判帧冻结）。
  Test C2 无相机的 OOD 敏感性探针：对一帧 tub 图像做平移/亮度/镜像等
           扰动，观察输出是否坍缩——区分“模型对输入不敏感”（H-B）与
           “输入本身定格”（H-A）。

用法（仓库 .venv 解释器）：
  .venv/bin/python tools/diagnose_pilot.py [--car-dir ~/projects/mycar] \
      [--model models/test-md-1.tflite] [--samples 150] \
      [--live 30] [--skip-live] [--no-c2]
"""

import argparse
import hashlib
import json
import os
import statistics
import sys
import time

import numpy as np

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)


def parse_args():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--car-dir', default='/home/dkc/projects/mycar',
                   help='车端工作目录（含 myconfig.py / data / models）')
    p.add_argument('--model', default=None,
                   help='模型路径；缺省读 selected_model.json，再退回 test-md-1.tflite')
    p.add_argument('--samples', type=int, default=150, help='Test A/B 抽样帧数')
    p.add_argument('--live', type=int, default=30, help='Test C 采样秒数')
    p.add_argument('--skip-live', action='store_true', help='跳过 Test C（不占相机）')
    p.add_argument('--no-c2', action='store_true', help='跳过 Test C2')
    p.add_argument('--out-dir', default='/tmp/diagnose_pilot',
                   help='Test C 样图落盘目录')
    return p.parse_args()


def resolve_model_path(car_dir, arg_model):
    if arg_model:
        path = arg_model if os.path.isabs(arg_model) else os.path.join(car_dir, arg_model)
        return os.path.normpath(path)
    selected = os.path.join(car_dir, 'selected_model.json')
    if os.path.isfile(selected):
        try:
            with open(selected) as f:
                return json.load(f)['model_path']
        except Exception:
            pass
    fallback = os.path.join(car_dir, 'models', 'test-md-1.tflite')
    if os.path.isfile(fallback):
        return fallback
    raise SystemExit(f'未找到模型：请在 --model 指定路径（car-dir={car_dir}）')


def load_labels(car_dir):
    """catalog_*.catalog → {index: (user/angle, user/throttle)}"""
    data_dir = os.path.join(car_dir, 'data')
    labels = {}
    for name in sorted(os.listdir(data_dir)):
        if not name.endswith('.catalog'):
            continue
        with open(os.path.join(data_dir, name)) as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                labels[int(rec['_index'])] = (
                    float(rec.get('user/angle', 0.0)),
                    float(rec.get('user/throttle', 0.0)))
    return labels


def load_image(car_dir, index):
    from PIL import Image
    path = os.path.join(car_dir, 'data', 'images', f'{index}_cam_image_array_.jpg')
    if not os.path.isfile(path):
        return None
    return np.asarray(Image.open(path).convert('RGB'))


def fmt_stats(values):
    if not values:
        return 'n=0'
    return (f'n={len(values):4d} min={min(values):+.3f} max={max(values):+.3f} '
            f'mean={statistics.fmean(values):+.3f} std={statistics.pstdev(values):.3f}')


def mae(a, b):
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


# ── Test A/B：tub 图像，两种预处理路径对照 ───────────────────────────────────
def run_tub_tests(car_dir, model_path, samples):
    import cv2
    from donkeycar.config import load_config
    from donkeycar.parts.pilot_holder import PilotHolder
    from donkeycar.utils import get_model_by_type

    print(f'── 加载模型（与车端 PilotHolder 完全同构）：{model_path}')
    # 与 arena 后端 load_car_config 同口径：载入车端 config.py（含默认值，
    # 尾部合并 myconfig.py），只用 myconfig 会缺 IMAGE_DEPTH 等默认键
    cfg = load_config(os.path.join(car_dir, 'config.py'))
    holder = PilotHolder(cfg, output_count=2)
    holder.load(model_path, 'tflite_linear')
    pilot = holder.current()
    in_shape = tuple(int(d) for d in pilot.get_input_shape('img_in')[-3:])
    h, w = in_shape[0], in_shape[1]
    print(f'   模型输入 (H,W,C)={in_shape}；解释器 {type(pilot.interpreter).__name__}')

    labels = load_labels(car_dir)
    if not labels:
        raise SystemExit('tub catalog 为空，无法对照标签')
    total = max(labels)
    step = max(1, total // samples)
    indexes = [i for i in range(0, total + 1, step)][:samples]

    out_a, out_b, label_a, label_t = [], [], [], []
    for idx in indexes:
        img = load_image(car_dir, idx)
        if img is None:
            continue
        # Test A：arena 式预处理（PIL RGB + cv2 拉伸到模型尺寸）+ 直接 pilot.run
        img_a = img if (img.shape[0] == h and img.shape[1] == w) else cv2.resize(img, (w, h))
        angle_a, throttle_a = pilot.run(np.asarray(img_a))
        # Test B：原始 320x240 走 PilotHolder（letterbox 适配）
        angle_b, throttle_b = holder.run(img)
        out_a.append((float(angle_a), float(throttle_a)))
        out_b.append((float(angle_b), float(throttle_b)))
        label_a.append(labels[idx][0])
        label_t.append(labels[idx][1])

    angles_a = [o[0] for o in out_a]
    throttles_a = [o[1] for o in out_a]
    angles_b = [o[0] for o in out_b]
    throttles_b = [o[1] for o in out_b]
    print(f'── Test A（arena 预处理，{len(out_a)} 帧）')
    print(f'   angle   {fmt_stats(angles_a)}')
    print(f'   throttle{fmt_stats(throttles_a)}')
    print(f'   与 tub 标签对比 MAE: angle={mae(angles_a, label_a):.4f} '
          f'throttle={mae(throttles_a, label_t):.4f}')
    print(f'   标签分布 angle {fmt_stats(label_a)}')
    print('── Test B（PilotHolder letterbox 路径）')
    print(f'   angle   {fmt_stats(angles_b)}')
    print(f'   throttle{fmt_stats(throttles_b)}')
    max_diff = max(max(abs(a - b) for a, b in zip(angles_a, angles_b)),
                   max(abs(a - b) for a, b in zip(throttles_a, throttles_b)))
    print(f'   A/B 最大偏差 {max_diff:.4f}（<0.02 视为口径一致）')
    return pilot, holder, angles_a, throttles_a


# ── Test C2：扰动敏感性探针（无相机）───────────────────────────────────────
def run_perturbation_probe(car_dir, holder):
    """对一帧 tub 图像做几何/光度扰动：健康模型输出应明显变化。"""
    from PIL import Image
    labels = load_labels(car_dir)
    idx = max(labels) // 2  # 取中段一帧
    path = os.path.join(car_dir, 'data', 'images', f'{idx}_cam_image_array_.jpg')
    img = np.asarray(Image.open(path).convert('RGB'))

    variants = {'原图': img}
    variants['右移40px'] = np.roll(img, 40, axis=1)
    variants['左移40px'] = np.roll(img, -40, axis=1)
    variants['上移30px'] = np.roll(img, -30, axis=0)
    variants['亮度x0.6'] = (img.astype(np.float64) * 0.6).astype(np.uint8)
    variants['亮度x1.4'] = np.clip(img.astype(np.float64) * 1.4, 0, 255).astype(np.uint8)
    variants['水平镜像'] = img[:, ::-1, :]
    variants['上半遮挡'] = np.concatenate(
        [np.full_like(img[:img.shape[0] // 2, :], 255), img[img.shape[0] // 2:]], axis=0)

    print(f'── Test C2（扰动敏感性，基准帧 index={idx}）')
    results = []
    for name, v in variants.items():
        angle, throttle = holder.run(np.ascontiguousarray(v))
        results.append((name, float(angle), float(throttle)))
        print(f'   {name:8s} angle={float(angle):+.4f} throttle={float(throttle):+.4f}')
    angles = [r[1] for r in results]
    spread = max(angles) - min(angles)
    print(f'   angle 扰动极差 {spread:.4f}（健康模型应显著大于 0；≈0 ⇒ 输出坍缩，支持 H-B）')
    return spread


# ── Test C：实时相机帧新鲜度 + 输出变化 ─────────────────────────────────────
def run_live_test(car_dir, holder, seconds, out_dir):
    from donkeycar.parts.camera import Webcam
    from PIL import Image

    print(f'── Test C（pygame Webcam 实时采样 {seconds}s，请移动小车/在镜头前挥动物体）')
    cam = Webcam(image_w=320, image_h=240, image_d=3, camera_index=0)
    os.makedirs(out_dir, exist_ok=True)

    intervals, outputs, hashes = [], [], set()
    saved = 0
    last_t = time.time()
    deadline = last_t + seconds
    frame = None
    while time.time() < deadline:
        frame = cam.run()
        if frame is None:
            time.sleep(0.005)
            continue
        now = time.time()
        intervals.append(now - last_t)
        last_t = now
        hashes.add(hashlib.sha1(np.ascontiguousarray(frame).tobytes()).hexdigest()[:12])
        angle, throttle = holder.run(frame)
        outputs.append((float(angle), float(throttle)))
        if saved < 3 and len(outputs) % max(1, seconds * 2) == 0:
            Image.fromarray(np.ascontiguousarray(frame)).save(
                os.path.join(out_dir, f'live_{saved}.jpg'))
            saved += 1
        time.sleep(0.03)
    cam.shutdown()

    angles = [o[0] for o in outputs]
    throttles = [o[1] for o in outputs]
    median_itv = statistics.median(intervals) if intervals else float('nan')
    unique_ratio = len(hashes) / len(outputs) if outputs else 0.0
    print(f'   采样 {len(outputs)} 帧；帧间隔中位数 {median_itv * 1000:.1f}ms；'
          f'唯一内容帧占比 {unique_ratio * 100:.0f}%')
    print(f'   angle   {fmt_stats(angles)}')
    print(f'   throttle{fmt_stats(throttles)}')
    print(f'   样图已存 {out_dir}/live_*.jpg（目检方向/颜色/曝光）')
    return median_itv, unique_ratio, angles


def main():
    args = parse_args()
    car_dir = os.path.abspath(os.path.expanduser(args.car_dir))
    model_path = resolve_model_path(car_dir, args.model)
    print(f'车端目录 {car_dir}\n模型 {model_path}\n')

    pilot, holder, angles_a, throttles_a = run_tub_tests(car_dir, model_path, args.samples)
    spread = None if args.no_c2 else run_perturbation_probe(car_dir, holder)

    median_itv = unique_ratio = None
    angles_c = []
    if not args.skip_live:
        median_itv, unique_ratio, angles_c = run_live_test(
            car_dir, holder, args.live, args.out_dir)

    # ── 判读 ────────────────────────────────────────────────────────────────
    print('\n══ 判读 ══')
    a_std = statistics.pstdev(angles_a) if angles_a else 0.0
    print(f'Test A angle std={a_std:.3f}（对照基准）')
    if spread is not None:
        verdict = '输出对扰动不敏感 ⇒ 支持模型坍缩（H-B：数据/模型问题）' \
            if spread < 0.05 else '输出对扰动敏感 ⇒ 模型本身正常'
        print(f'Test C2 极差={spread:.3f}：{verdict}')
    if median_itv is not None:
        if unique_ratio < 0.5 or median_itv > 0.5:
            print(f'Test C 帧疑似停滞（唯一帧 {unique_ratio * 100:.0f}%，中位间隔 '
                  f'{median_itv * 1000:.0f}ms）⇒ 支持相机帧冻结（H-A）')
        else:
            c_std = statistics.pstdev(angles_c) if len(angles_c) > 1 else 0.0
            print(f'Test C 帧新鲜（唯一帧 {unique_ratio * 100:.0f}%），angle std={c_std:.3f}'
                  f'（std≪Test A 且场景确有移动 ⇒ 支持实时画面 OOD 坍缩 H-B）')
    if args.skip_live:
        print('（Test C 已跳过；如需判帧冻结请停车端进程后去掉 --skip-live 重跑）')


if __name__ == '__main__':
    main()
