# -*- coding: utf-8 -*-
"""批量把旧 tub 的鱼眼图像展平为去畸变后的标准视野图像。

tub v2 的元数据（catalog_*.catalog）只记录图像文件名、不记录图像尺寸，
因此只要输出分辨率与输入一致，替换 images/ 下的图片即可，无需改动元数据。

为保持 tub 颜色语义（tub 以 PIL 按 RGB 保存），读取与写回均使用 PIL。

用法：
    # 生成一个展平后的新 tub（非破坏性，推荐）
    python scripts/undistort_tub.py --tub /home/dkc/projects/mycar/data \
        --out /home/dkc/projects/mycar/data_undistorted --car /home/dkc/projects/mycar

    # 原地覆盖（会先备份原图为 <tub>_backup）
    python scripts/undistort_tub.py --tub /home/dkc/projects/mycar/data --in-place --yes

    # 手工指定成像圆 / 指定输出 FOV
    python scripts/undistort_tub.py --tub data --circle 157,124,106 --fov 120
"""
import argparse
import glob
import logging
import os
import shutil
import sys
import time
import types
from multiprocessing import Pool

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from donkeycar.parts.fisheye import FisheyeUndistort, estimate_image_circle  # noqa: E402

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("undistort_tub")

_WORKER = {}


def _build_config(car_dir, circle, fov):
    """合并车辆配置与本次运行的成像圆/输出 FOV，返回可用的配置对象。"""
    values = {}
    config_path = os.path.join(car_dir, "config.py") if car_dir else None
    if config_path and os.path.exists(config_path):
        from donkeycar.config import load_config
        cfg = load_config(config_path)
        for key in ("FISHEYE_FOV_DEG", "FISHEYE_MAX_BLACK", "FISHEYE_WIDTH",
                    "FISHEYE_HEIGHT", "FISHEYE_OUT_FOV_DEG", "FISHEYE_INTRINSICS"):
            if hasattr(cfg, key):
                values[key] = getattr(cfg, key)
        circle = circle or getattr(cfg, "FISHEYE_CIRCLE", None)
    if circle:
        values["FISHEYE_CIRCLE"] = tuple(circle)
    if fov:
        values["FISHEYE_OUT_FOV_DEG"] = float(fov)
    values.setdefault("FISHEYE_FOV_DEG", 160.0)
    return types.SimpleNamespace(**values)


def _init_worker(src_images, dst_images, cfg_values, quality):
    cfg = types.SimpleNamespace(**cfg_values)
    _WORKER["src"] = src_images
    _WORKER["dst"] = dst_images
    _WORKER["quality"] = quality
    _WORKER["part"] = FisheyeUndistort(cfg)


def _process_one(name):
    src = os.path.join(_WORKER["src"], name)
    dst = os.path.join(_WORKER["dst"], name)
    try:
        with Image.open(src) as im:
            arr = np.asarray(im.convert("RGB"))
        out = _WORKER["part"].run(arr)
        Image.fromarray(np.uint8(out)).save(dst, quality=_WORKER["quality"])
        return None
    except Exception as exc:  # noqa: BLE001 - 逐张容错，不中断整体批处理
        return f"{name}: {exc}"


def main() -> int:
    parser = argparse.ArgumentParser(description="批量把旧 tub 的鱼眼图像展平为标准视野")
    parser.add_argument("--tub", required=True, help="源 tub 目录（含 images/ 与 catalog_*）")
    parser.add_argument("--out", help="输出 tub 目录；缺省为 <tub>_undistorted")
    parser.add_argument("--in-place", action="store_true", help="原地覆盖源 tub（会先备份）")
    parser.add_argument("--yes", action="store_true", help="确认原地覆盖，跳过二次确认")
    parser.add_argument("--car", help="车辆目录（用于读取 myconfig.py 中的 FISHEYE_* 配置）")
    parser.add_argument("--circle", help="成像圆覆盖值，格式 cx,cy,r")
    parser.add_argument("--fov", type=float, help="固定输出水平视场角(度)")
    parser.add_argument("--quality", type=int, default=95, help="JPEG 质量，默认 95")
    parser.add_argument("--workers", type=int, default=0, help="并行进程数，0=CPU 核数")
    args = parser.parse_args()

    tub = os.path.abspath(args.tub)
    src_images = os.path.join(tub, "images")
    if not os.path.isdir(src_images):
        print(f"未找到 tub 的 images 目录: {src_images}")
        return 1

    circle = None
    if args.circle:
        parts = [float(v) for v in args.circle.split(",")]
        if len(parts) != 3:
            print("--circle 需为 cx,cy,r 三个数值")
            return 1
        circle = tuple(parts)

    car_dir = args.car or (os.path.dirname(tub) if os.path.exists(
        os.path.join(os.path.dirname(tub), "config.py")) else None)
    cfg = _build_config(car_dir, circle, args.fov)

    files = sorted(os.path.basename(p) for p in glob.glob(os.path.join(src_images, "*.jpg")))
    if not files:
        print(f"{src_images} 下没有 .jpg 图像")
        return 1

    # 成像圆在运行前确定一次，保证整批使用完全一致的映射
    if getattr(cfg, "FISHEYE_CIRCLE", None) is None:
        sample = np.asarray(Image.open(os.path.join(src_images, files[len(files) // 2])).convert("RGB"))
        cx, cy, r = estimate_image_circle(sample)
        cfg.FISHEYE_CIRCLE = (cx, cy, r)
        print(f"自动检测成像圆: ({cx:.0f}, {cy:.0f}) r={r:.1f}")

    # 确定输出目录
    if args.in_place:
        if not args.yes:
            ans = input(f"将原地覆盖 {tub} 下的图像（会先备份），确认？[y/N] ")
            if ans.strip().lower() not in ("y", "yes"):
                print("已取消")
                return 1
        backup = tub.rstrip(os.sep) + "_backup"
        if os.path.exists(backup):
            print(f"备份目录已存在，为免覆盖请先移除: {backup}")
            return 1
        print(f"备份原 tub -> {backup}")
        shutil.copytree(tub, backup)
        out_tub, dst_images = tub, src_images
    else:
        out_tub = os.path.abspath(args.out) if args.out else tub.rstrip(os.sep) + "_undistorted"
        if os.path.exists(out_tub):
            print(f"输出目录已存在，请先移除: {out_tub}")
            return 1
        os.makedirs(os.path.join(out_tub, "images"))
        dst_images = os.path.join(out_tub, "images")
        # 复制 tub 非图像内容（catalog / manifest 等）
        for entry in os.listdir(tub):
            if entry == "images":
                continue
            s, d = os.path.join(tub, entry), os.path.join(out_tub, entry)
            if os.path.isdir(s):
                shutil.copytree(s, d)
            else:
                shutil.copy2(s, d)
        print(f"输出到新 tub: {out_tub}")

    workers = args.workers or (os.cpu_count() or 1)
    cfg_values = vars(cfg)
    print(f"开始处理 {len(files)} 张图像，并行 {workers} 进程...")
    t0 = time.time()
    errors = []
    if workers > 1:
        with Pool(workers, initializer=_init_worker,
                  initargs=(src_images, dst_images, cfg_values, args.quality)) as pool:
            for err in pool.imap_unordered(_process_one, files, chunksize=64):
                if err:
                    errors.append(err)
    else:
        _init_worker(src_images, dst_images, cfg_values, args.quality)
        for name in files:
            err = _process_one(name)
            if err:
                errors.append(err)

    dt = time.time() - t0
    print(f"完成：{len(files) - len(errors)}/{len(files)} 张，用时 {dt:.1f}s（{len(files)/max(dt,1e-6):.0f} 张/秒）")
    if errors:
        print(f"失败 {len(errors)} 张，示例：")
        for e in errors[:10]:
            print("  ", e)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
