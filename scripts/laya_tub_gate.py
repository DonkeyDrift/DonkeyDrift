#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
laya_tub_gate.py —— 用 Laya（或纯规则）给 Donkeycar 的 tub 做离线数据质量阀门

核心思路
--------
Laya 是文本决策模型（ModernBERT 主干），它【看不了图像】。
所以不要指望它直接读 cam/image_array 判断"是否出界"。
正确做法是搭一座桥：把每个时间窗压成十几个【数值特征】，
再把数值渲染成结构化文本喂给 Laya，让它在"元特征"层面做判断。

这座桥带来两个好处：
  1. 完全离线，不碰 20Hz 实时链路 → 对行车零风险
  2. 输入维度极小，批处理很快，1 万帧约几分钟跑完

四种模式
--------
  report    只出诊断报告（默认，绝不改动你的 tub）
  delete    把坏窗口覆盖的记录交给 Tub.delete_records()（官方软删除接口，不手改 catalog）
  export    导出一个清洗 + 平衡过的新 tub，原数据不动（推荐）
  eval      不需要 tub：用合成标注窗口做引擎 A/B（准确率 + ECE 校准对比）；
            也可用 --labels 指向人工标注过的 report jsonl 做真实数据校准评估
两个引擎
--------
  heuristic  纯阈值规则（约 20 行），零依赖、零训练，【默认引擎】
             合成基准实测 99% 准确率 / ECE 0.084，缺陷归因 99%
  laya       文本决策模型。零样本实测仅为多数类基线（见 README"实测记录"），
             且官方承认出厂 checkpoint 过度自信——严肃使用前应先用标注数据
             拟合温度（laya.fit_temperatures），再用 --labels 复评

依赖
----
  report/eval(heuristic): numpy + pillow（pillow 仅在读取视觉特征时需要）
  eval/打分(laya):        pip install laya （拖带 torch/transformers，约 2GB）
  delete/export:          需要本仓库 donkeycar（Tub 官方接口）

用法
----
  python scripts/laya_tub_gate.py --tub ~/mycar/data/tub_001 --mode report
  python scripts/laya_tub_gate.py --tub ~/mycar/data/tub_001 --mode report --engine heuristic
  python scripts/laya_tub_gate.py --tub ~/mycar/data/tub_001 --mode delete --threshold 0.35
  python scripts/laya_tub_gate.py --tub ~/mycar/data/tub_001 --mode export --out ~/mycar/data/tub_clean \
         --balance --straight-keep 0.5
  python scripts/laya_tub_gate.py --mode eval                     # 合成基准：规则 vs Laya
  python scripts/laya_tub_gate.py --mode eval --labels annotated.jsonl --engine laya
"""

import argparse
import glob
import json
import os
import sys
import time
from collections import Counter

import numpy as np

# ----------------------------------------------------------------------
# 1. 读取 tub
#
# tub_v2 的 catalog 是"每行一个 JSON 对象"的 jsonl，不能 json.load() 整体读；
# v1 则是每帧一个 record_*.json 文件。两种都兼容，且都对 _deleted 软删除跳过。
# ----------------------------------------------------------------------

META_KEYS = ("_index", "_session_id", "_timestamp_ms", "timestamp_ms", "_deleted")

# 图像缩到这个尺寸做视觉元特征：再大不增加判别力，只浪费 IO 和内存
GRAY_SIZE = (64, 48)


def _numeric_sort_key(path):
    """按文件名里的数字排序：catalog_2 < catalog_10（字典序会排反）。"""
    return int("".join(ch for ch in os.path.basename(path) if ch.isdigit()) or 0)


def _manifest_deleted_indexes(tub_path):
    """从 manifest.json 读软删除索引集合。

    tub_v2 的 delete_records() 只把索引记进 manifest 的 deleted_indexes，
    catalog 行内不会有任何标记——只看 `_deleted` 字段会把已删记录当成活记录读回来。
    """
    mani_path = os.path.join(tub_path, "manifest.json")
    if not os.path.exists(mani_path):
        return set()
    try:
        with open(mani_path, "r", encoding="utf-8") as fp:
            lines = [l.strip() for l in fp if l.strip()]
        for l in lines:
            try:
                obj = json.loads(l)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and "deleted_indexes" in obj:
                return set(obj.get("deleted_indexes") or [])
    except Exception:
        pass
    return set()


def load_tub_records(tub_path):
    """读 tub（v2 优先，回退 v1）。返回 (records, inputs, types)。

    保证返回的每条记录都带 `_index`（v1 没有就补上位置号），
    下游所有索引一律用 `_index`，避免"位置"和"索引"两套坐标系混用。
    """
    if not os.path.isdir(tub_path):
        sys.exit(f"[x] tub 目录不存在: {tub_path}")

    cat_files = sorted(
        glob.glob(os.path.join(tub_path, "catalog_*.catalog")), key=_numeric_sort_key
    )
    fmt = "v2"
    if not cat_files:
        cat_files = sorted(
            glob.glob(os.path.join(tub_path, "record_*.json")), key=_numeric_sort_key
        )
        fmt = "v1"
    if not cat_files:
        sys.exit(f"[x] 在 {tub_path} 下找不到 catalog_*.catalog 或 record_*.json，不是有效的 tub 目录")

    deleted = _manifest_deleted_indexes(tub_path) if fmt == "v2" else set()
    records = []
    for f in cat_files:
        with open(f, "r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue  # 坏行直接跳过——这类正是本工具要清掉的垃圾
                if rec.get("_deleted") or rec.get("_index") in deleted:
                    continue
                records.append(rec)
    if not records:
        sys.exit(f"[x] {tub_path} 里没有可用的未删除记录（格式 {fmt}）")

    # 注意：跳过已删记录之后 records 的位置和 _index 不再相等（有空洞），
    # 所以这里不能 sort 后用位置当索引，必须保留原始 _index。
    records.sort(key=lambda r: r.get("_index", 0))
    for pos, rec in enumerate(records):
        rec.setdefault("_index", pos)

    # inputs/types：优先 meta.json（v1），其次 manifest.json（v2），最后从记录键推断
    inputs, types = _load_meta(tub_path)
    if not inputs:
        keys = [k for k in records[0].keys() if k not in META_KEYS]
        inputs = keys
        types = ["image_array" if "image" in k else "float" for k in keys]
    return records, inputs, types


def _load_meta(tub_path):
    """v1 的 schema 在 meta.json；v2 的在 manifest.json 前几行（jsonl 风格）。"""
    meta_path = os.path.join(tub_path, "meta.json")
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as fp:
                meta = json.load(fp)
            return meta.get("inputs"), meta.get("types")
        except Exception:
            pass
    mani_path = os.path.join(tub_path, "manifest.json")
    if os.path.exists(mani_path):
        try:
            # manifest.json 行序：inputs, types, metadata, manifest_metadata, catalog 元数据
            # 前 5 行里最先出现的两个"纯字符串列表"就是 inputs 和 types
            with open(mani_path, "r", encoding="utf-8") as fp:
                lines = [l.strip() for l in fp if l.strip()][:5]
            str_lists = []
            for l in lines:
                try:
                    obj = json.loads(l)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, list) and obj and all(isinstance(x, str) for x in obj):
                    str_lists.append(obj)
            if len(str_lists) >= 2:
                return str_lists[0], str_lists[1]
        except Exception:
            pass
    return None, None


def resolve_image_path(tub_path, rec):
    """定位一帧图像文件。v2 在 images/ 子目录，老版本可能在根目录；失败返回 None。"""
    rel = rec.get("cam/image_array")
    if not rel:
        return None
    p = rel if os.path.isabs(rel) else os.path.join(tub_path, rel)
    if not os.path.exists(p):
        p = os.path.join(tub_path, "images", os.path.basename(rel))
    return p if os.path.exists(p) else None


def load_gray(tub_path, rec):
    """读一帧为归一化灰度小图（64×48），用于算廉价视觉元特征。失败返回 None。"""
    from PIL import Image

    p = resolve_image_path(tub_path, rec)
    if not p:
        return None
    try:
        img = Image.open(p).convert("L").resize(GRAY_SIZE)
        return np.asarray(img, dtype=np.float32) / 255.0
    except Exception:
        return None


def load_rgb(tub_path, rec):
    """读一帧原始 RGB 数组。仅 export 模式使用（要保真，不能拿 64×48 灰度图充数）。"""
    from PIL import Image

    p = resolve_image_path(tub_path, rec)
    if not p:
        return None
    try:
        return np.asarray(Image.open(p).convert("RGB"))
    except Exception:
        return None


# ----------------------------------------------------------------------
# 2. 特征工程：图像/遥测 → 十几个数
# ----------------------------------------------------------------------

def window_features(win, gray_by_index):
    """win 是连续 N 帧的 record 列表；gray_by_index 按 _index 提供灰度小图。

    返回 dict。视觉特征拿不到时填 -1（区别于"真实的低运动量 0"）。
    """
    ang = np.array([float(r.get("user/angle", 0.0)) for r in win], dtype=np.float32)
    thr = np.array([float(r.get("user/throttle", 0.0)) for r in win], dtype=np.float32)
    # v2 实际写的是 _timestamp_ms，老数据里可能是 timestamp_ms，两个都试
    tkey = "_timestamp_ms" if "_timestamp_ms" in win[0] else "timestamp_ms"
    ts = np.array([float(r.get(tkey, 0.0)) for r in win], dtype=np.float64)
    dt = np.diff(ts)
    dt = dt[np.isfinite(dt) & (dt > 0)]

    f = {
        "angle_mean":      float(np.mean(ang)),
        "angle_std":       float(np.std(ang)),
        "angle_jerk":      float(np.mean(np.abs(np.diff(ang)))),   # 平均逐帧转向变化
        "angle_max_step":  float(np.max(np.abs(np.diff(ang)))) if len(ang) > 1 else 0.0,
        "angle_zero_cross": int(np.sum(np.diff(np.sign(ang)) != 0)),  # 来回打舵次数
        "thr_mean":        float(np.mean(thr)),
        "thr_std":         float(np.std(thr)),
        "thr_zero_ratio":  float(np.mean(thr < 0.02)),             # 松油门/停车占比
        "dt_ms_mean":      float(np.mean(dt)) if len(dt) else 0.0,
        "dt_ms_std":       float(np.std(dt)) if len(dt) else 0.0,  # 帧间隔抖动→掉帧/IO 卡顿
    }

    # 廉价视觉元特征：窗口内相邻帧差异（撞墙后车不动 → 接近 0）
    grays = [gray_by_index.get(r["_index"]) for r in win]
    grays = [g for g in grays if g is not None]
    if len(grays) >= 2:
        diffs = [float(np.mean(np.abs(grays[i + 1] - grays[i]))) for i in range(len(grays) - 1)]
        f["frame_motion"] = float(np.mean(diffs))
        f["frame_motion_std"] = float(np.std(diffs))
        f["brightness"] = float(np.mean(grays[-1]))
        f["brightness_delta"] = float(np.mean(grays[-1]) - np.mean(grays[0]))
    else:
        f["frame_motion"] = -1.0
        f["frame_motion_std"] = -1.0
        f["brightness"] = -1.0
        f["brightness_delta"] = 0.0
    return f


def render_state(f):
    """把数值渲染成 Laya 能读的结构化文本。

    这是全脚本最关键的一步：喂什么文本，决定 Laya 判断力的上限。
    用 key=value 的紧凑格式、英文键名，对英文主干（ModernBERT）最稳。
    想用中文描述就换 --model convaiinnovations/laya-multilingual。
    """
    return (
        f"RC car driving window, {f['n_frames']} frames @20Hz.\n"
        f"steering: mean={f['angle_mean']:.3f} std={f['angle_std']:.3f} "
        f"jerk={f['angle_jerk']:.4f} max_step={f['angle_max_step']:.3f} "
        f"zero_crossings={f['angle_zero_cross']}\n"
        f"throttle: mean={f['thr_mean']:.3f} std={f['thr_std']:.3f} "
        f"zero_ratio={f['thr_zero_ratio']:.2f}\n"
        f"timing: dt_ms_mean={f['dt_ms_mean']:.1f} dt_ms_std={f['dt_ms_std']:.1f}\n"
        f"vision: frame_motion={f['frame_motion']:.4f} "
        f"brightness={f['brightness']:.3f} brightness_delta={f['brightness_delta']:+.3f}"
    )


# ----------------------------------------------------------------------
# 3. Laya 提问设计：一次前向，四个问题同时出结果
# ----------------------------------------------------------------------

QUESTIONS = {
    # Noul → 0.0~1.0 的校准概率，直接当阈值或软权重用
    "is_clean": {
        "type": "noul",
        "instructions": (
            "This telemetry window is defect-free and usable as supervised "
            "imitation-learning data: the car was moving, on track, steering "
            "smoothly, with no crash, no stall, no off-track excursion and "
            "no sensor/IO glitch."
        ),
    },
    # Score → 有序等级，用来做数据分档和补采优先级
    "quality": {
        "type": "score",
        "instructions": "Overall quality of this driving window for imitation learning.",
        "criteria": ["garbage", "poor", "marginal", "good", "excellent"],
    },
    # Choice → 缺陷归因，用来决定"删"还是"补采"
    "defect": {
        "type": "choice",
        "instructions": "Primary defect of this window, if any.",
        "criteria": {
            "none":              "clean, smooth, on-track driving",
            "stationary_stall":  "car stopped or barely moving, frames nearly identical",
            "off_track":         "left the track, scene changed abruptly, abnormal brightness",
            "erratic_steering":  "steering oscillates or snaps sharply back and forth",
            "throttle_chop":     "throttle repeatedly cut to zero or wildly unstable",
            "sensor_glitch":     "frame timing irregular, dropped frames, empty or corrupt image",
        },
    },
    # Choice → 机动类型，用来做类别平衡（驴车数据 80% 是直行，这条最值钱）
    "maneuver": {
        "type": "choice",
        "instructions": "Dominant maneuver in this window.",
        "criteria": {
            "straight": "driving essentially straight",
            "left":     "sustained left turn",
            "right":    "sustained right turn",
            "brake":    "decelerating or stopped",
        },
    },
}


def laya_score_all(states, model_name, batch_size=32):
    """跑 Laya 引擎。有 predict_batch 就批量（GPU 上快数倍），没有就逐条。"""
    # scripts/ 目录里的历史脚本名（如 profile.py）会遮蔽标准库同名模块；
    # `python scripts/laya_tub_gate.py` 会把 scripts/ 放进 sys.path 首位，
    # 让 transformers 的懒加载链 import 到仓库脚本而非 stdlib，报出
    # "No module named 'donkeycar'" 这种完全不相干的错。
    # laya 引擎不依赖 scripts/ 里的任何东西，导入前把它摘掉。
    _here = os.path.dirname(os.path.abspath(__file__))
    sys.path[:] = [p for p in sys.path if os.path.abspath(p or ".") != _here]
    try:
        import laya
    except ImportError:
        sys.exit("[x] 未安装 laya。先 `pip install laya`（拖带 torch/transformers，约 2GB），"
                 "或改用 --engine heuristic 跑规则基线。")
    print(f"      加载模型 {model_name}（首次会从 HuggingFace 下载权重）...")
    agent = laya.load(model_name)

    def _parse(res):
        a = res["answers"]
        # score 原语返回期望等级（浮点）+ legend 映射；两个都留：
        # 数值可排序求均值，标签可读。拿不到时降级为 "?" 不中断批处理。
        q = a.get("quality", {})
        legend = q.get("legend") or {}
        try:
            qval = float(q.get("score"))
            qlabel = legend.get(str(int(round(qval))), "?")
        except (TypeError, ValueError):
            qval, qlabel = None, str(q.get("score", "?"))
        return {
            "is_clean": float(a["is_clean"]["noul"]),
            "quality": qlabel,
            "quality_level": qval,
            "defect":   a.get("defect", {}).get("choice", "?"),
            "maneuver": a.get("maneuver", {}).get("choice", "?"),
        }

    out = []
    t0 = time.time()
    predict_batch = getattr(agent, "predict_batch", None)
    for i in range(0, len(states), batch_size):
        chunk = states[i:i + batch_size]
        if predict_batch is not None:
            out.extend(_parse(r) for r in predict_batch(chunk, QUESTIONS))
        else:
            out.extend(_parse(agent.predict(st, QUESTIONS)) for st in chunk)
        done = min(i + batch_size, len(states))
        if done % 500 < batch_size or done == len(states):
            rate = done / max(time.time() - t0, 1e-6)
            print(f"    ... {done}/{len(states)}  ({rate:.0f} 窗口/秒)", flush=True)
    return out


def heuristic_score_all(feats_list):
    """规则基线：不用 Laya，纯阈值。

    【强烈建议先跑它】只有当 eval 模式证明 Laya 明显强于这 20 行规则时，
    引入 Laya 才是划算的。用它做 A/B 对照，别盲目替换。
    阈值针对 20Hz、常规赛道/光照调的，换环境需要重新标定。
    """
    out = []
    for f in feats_list:
        clean, defect = 1.0, "none"
        if 0 <= f["frame_motion"] < 0.004:
            clean, defect = 0.05, "stationary_stall"
        elif f["angle_jerk"] > 0.18 or f["angle_zero_cross"] >= 6:
            clean, defect = 0.15, "erratic_steering"
        elif f["thr_zero_ratio"] > 0.7:
            clean, defect = 0.25, "throttle_chop"
        elif f["dt_ms_std"] > 30:
            clean, defect = 0.2, "sensor_glitch"
        elif 0 <= f["frame_motion"] and abs(f["brightness_delta"]) > 0.15:
            clean, defect = 0.3, "off_track"

        if clean > 0.8:
            q = "excellent" if f["angle_std"] < 0.05 else "good"
        elif clean > 0.5:
            q = "marginal"
        else:
            q = "garbage" if clean < 0.15 else "poor"

        m = f["angle_mean"]
        maneuver = "straight" if abs(m) < 0.08 else ("left" if m < 0 else "right")
        if f["thr_zero_ratio"] > 0.6:
            maneuver = "brake"
        out.append({"is_clean": clean, "quality": q, "defect": defect, "maneuver": maneuver})
    return out


# ----------------------------------------------------------------------
# 4. 决策：窗口结论 → 记录级 keep/drop
# ----------------------------------------------------------------------

def decide(feats_list, scores, threshold, balance, straight_keep, seed=0):
    """窗口级决策。返回 (keep, drop)，每个元素都带 indices（该窗口覆盖的真实 _index 列表）。

    语义说明：stride < window 时窗口重叠，一条记录会被多个窗口覆盖。
    这里取"保守并集"——任何一个覆盖它的窗口被判坏，该记录就进坏集合。
    缺陷（如撞墙静止）通常持续存在，宁可多删边界帧也不放过坏段。
    """
    rng = np.random.default_rng(seed)
    keep, drop = [], []
    for i, (f, s) in enumerate(zip(feats_list, scores)):
        verdict = {"win": i, "start": f["start"], "end": f["end"], "indices": f["indices"],
                   "is_clean": s["is_clean"], "quality": s["quality"],
                   "defect": s["defect"], "maneuver": s["maneuver"], "action": "keep"}
        if s["is_clean"] < threshold:
            verdict["action"] = "drop"
            drop.append(verdict)
            continue
        if balance and s["maneuver"] == "straight" and rng.random() > straight_keep:
            verdict["action"] = "downsample"
            drop.append(verdict)
            continue
        keep.append(verdict)
    return keep, drop


# ----------------------------------------------------------------------
# 5. eval 模式：合成标注基准 / 人工标注数据 的 准确率 + ECE 对比
# ----------------------------------------------------------------------

SYNTH_DEFECTS = ("stationary_stall", "erratic_steering", "throttle_chop",
                 "sensor_glitch", "off_track")


def _synth_window(rng, kind):
    """按缺陷类型生成一个"窗口特征"dict。数值范围参考 20Hz 驴车实测。

    注意：合成分布就是按规则引擎的阈值反过来构造的，天然偏向规则引擎。
    它能验证"规则在自家地盘是否自洽"、"Laya 是否具备基本判别力"，
    但不能替代真实标注数据上的对比——那一步用 --labels 走人工标注流程。
    """
    n = 10
    t = np.arange(n)
    if kind == "clean":
        # 平滑巡线：低频正弦 + 小噪声。幅度/频率上限压在 erratic 阈值之下，
        # 保证"干净"合成样本不会被规则误伤
        amp = rng.uniform(0.05, 0.3)
        ang = amp * np.sin(2 * np.pi * rng.uniform(0.3, 0.8) * t / n + rng.uniform(0, 6.28))
        ang += rng.normal(0, 0.01, n)
        thr = np.full(n, rng.uniform(0.4, 0.8)) + rng.normal(0, 0.02, n)
        dt_ms = rng.normal(50, 2.5, n - 1)
        motion = rng.uniform(0.008, 0.03)
        bright = rng.uniform(0.3, 0.5)
        bright_delta = rng.normal(0, 0.02)
    elif kind == "stationary_stall":
        ang = np.full(n, rng.uniform(-0.2, 0.2)) + rng.normal(0, 0.002, n)
        thr = np.zeros(n)
        dt_ms = rng.normal(50, 2.0, n - 1)
        motion = rng.uniform(0.0002, 0.0015)
        bright = rng.uniform(0.5, 0.75)
        bright_delta = rng.uniform(0.0, 0.03)
    elif kind == "erratic_steering":
        ang = rng.choice([-1, 1], n) * rng.uniform(0.5, 0.9) + rng.normal(0, 0.02, n)
        thr = np.full(n, rng.uniform(0.4, 0.6)) + rng.normal(0, 0.02, n)
        dt_ms = rng.normal(50, 2.5, n - 1)
        motion = rng.uniform(0.01, 0.03)
        bright = rng.uniform(0.3, 0.5)
        bright_delta = rng.normal(0, 0.02)
    elif kind == "throttle_chop":
        ang = 0.2 * np.sin(t / 4.0) + rng.normal(0, 0.01, n)
        # 10 帧里只有 2 帧点了一下油门（zero_ratio=0.8，越过 0.7 阈值），车仍在滑行
        thr = np.where((t == 0) | (t == 5), rng.uniform(0.55, 0.7), 0.0)
        dt_ms = rng.normal(50, 2.5, n - 1)
        motion = rng.uniform(0.005, 0.02)
        bright = rng.uniform(0.3, 0.5)
        bright_delta = rng.normal(0, 0.02)
    elif kind == "sensor_glitch":
        ang = 0.25 * np.sin(t / 5.0) + rng.normal(0, 0.01, n)
        thr = np.full(n, 0.55) + rng.normal(0, 0.02, n)
        dt_ms = np.abs(rng.normal(50, 3, n - 1))
        # 3 个互不重叠的帧间隔尖峰（掉帧/IO 卡顿），保证 std 稳定越过 30ms 阈值
        for j in rng.choice(n - 1, size=3, replace=False):
            dt_ms[j] += rng.uniform(40, 120)
        motion = rng.uniform(0.008, 0.025)
        bright = rng.uniform(0.3, 0.5)
        bright_delta = rng.normal(0, 0.02)
    elif kind == "off_track":
        # 冲出赛道：画面剧变（高 motion）+ 光照突变（大 brightness_delta）
        ang = 0.5 * np.sin(t / 4.0) + rng.normal(0, 0.02, n)
        thr = np.full(n, rng.uniform(0.5, 0.7)) + rng.normal(0, 0.02, n)
        dt_ms = rng.normal(50, 2.5, n - 1)
        motion = rng.uniform(0.03, 0.06)
        bright = rng.uniform(0.35, 0.55)
        bright_delta = -rng.uniform(0.18, 0.3)
    else:
        raise ValueError(kind)

    d_ang = np.diff(ang)
    return {
        "n_frames": n,
        "angle_mean": float(np.mean(ang)),
        "angle_std": float(np.std(ang)),
        "angle_jerk": float(np.mean(np.abs(d_ang))),
        "angle_max_step": float(np.max(np.abs(d_ang))),
        "angle_zero_cross": int(np.sum(np.diff(np.sign(ang)) != 0)),
        "thr_mean": float(np.mean(thr)),
        "thr_std": float(np.std(thr)),
        "thr_zero_ratio": float(np.mean(thr < 0.02)),
        "dt_ms_mean": float(np.mean(dt_ms)),
        "dt_ms_std": float(np.std(dt_ms)),
        "frame_motion": float(motion),
        "frame_motion_std": float(motion * 0.2),
        "brightness": float(bright),
        "brightness_delta": float(bright_delta),
    }


def synth_dataset(n_windows, seed=0, clean_ratio=0.6):
    """合成带真值的窗口集：clean 占 clean_ratio，五种缺陷均分剩余。"""
    rng = np.random.default_rng(seed)
    rows = []
    n_clean = int(n_windows * clean_ratio)
    n_defect = n_windows - n_clean
    for i in range(n_windows):
        if i < n_clean:
            kind = "clean"
        else:
            kind = SYNTH_DEFECTS[(i - n_clean) % len(SYNTH_DEFECTS)]
        rows.append((kind, _synth_window(rng, kind)))
    rng.shuffle(rows)
    return rows


def ece_and_reliability(probs, labels, n_bins=10):
    """ECE + 可靠性曲线数据。probs/labels 是 0~1 的概率和 0/1 真值。"""
    probs = np.asarray(probs, dtype=np.float64)
    labels = np.asarray(labels, dtype=np.float64)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece, rows = 0.0, []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (probs >= lo) & (probs < hi if hi < 1.0 else probs <= hi)
        n = int(m.sum())
        if n == 0:
            rows.append({"bin": [float(lo), float(hi)], "n": 0, "acc": None, "conf": None})
            continue
        acc, conf = float(labels[m].mean()), float(probs[m].mean())
        ece += n / len(probs) * abs(acc - conf)
        rows.append({"bin": [float(lo), float(hi)], "n": n, "acc": acc, "conf": conf})
    return float(ece), rows


def evaluate_engine(feats, states, labels, kinds, engine_fn, engine_name, threshold):
    scores = engine_fn(feats)
    probs = [s["is_clean"] for s in scores]
    preds = [1 if p >= threshold else 0 for p in probs]
    acc = float(np.mean([int(p == l) for p, l in zip(preds, labels)]))
    ece, rel = ece_and_reliability(probs, labels)
    # 干净窗口的期望归因是 "none"（kind 记作 "clean" 只是真值标签），缺陷窗口是缺陷名本身
    defect_acc = float(np.mean([s["defect"] == ("none" if k == "clean" else k)
                                for s, k in zip(scores, kinds)]))
    return {
        "engine": engine_name, "n": len(labels), "threshold": threshold,
        "accuracy": acc, "ece": ece, "defect_accuracy": defect_acc,
        "is_clean_mean": float(np.mean(probs)),
        "reliability": rel,
    }


def run_eval(args):
    """eval 模式：合成基准（默认）或 --labels 人工标注 jsonl 的校准评估。

    人工标注流程：先跑 report 模式得到 jsonl → 人工给每行加 "label_clean": 0/1
    （有缺陷填 0，可保留填 1）→ 用 --labels 指回这个文件重新评估两个引擎。
    """
    if args.labels:
        feats, states, labels, kinds = [], [], [], []
        with open(args.labels, "r", encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if "label_clean" not in row:
                    sys.exit("[x] --labels 文件里存在没有 label_clean 字段的行，"
                             "请先完成人工标注（1=干净可保留，0=有缺陷）")
                f = {k: row[k] for k in (
                    "angle_mean", "angle_std", "angle_jerk", "angle_max_step",
                    "angle_zero_cross", "thr_mean", "thr_std", "thr_zero_ratio",
                    "dt_ms_mean", "dt_ms_std", "frame_motion", "frame_motion_std",
                    "brightness", "brightness_delta")}
                f["n_frames"] = int(row.get("end", 0) - row.get("start", 0) + 1) or 10
                feats.append(f)
                states.append(render_state(f))
                labels.append(int(row["label_clean"]))
                kinds.append(row.get("defect", "unknown"))
        print(f"[eval] 读入人工标注窗口 {len(labels)} 个（正例 {sum(labels)}）")
    else:
        rows = synth_dataset(args.eval_windows, seed=args.seed)
        feats = [f for _, f in rows]
        states = [render_state(f) for f in feats]
        labels = [1 if k == "clean" else 0 for k, _ in rows]
        kinds = [k for k, _ in rows]
        print(f"[eval] 合成基准：{len(rows)} 窗口（clean {sum(labels)} / 缺陷 {len(rows)-sum(labels)}），"
              f"seed={args.seed}")

    engines = [("heuristic", lambda fs: heuristic_score_all(fs))]
    if args.engine == "laya":
        try:
            import laya  # noqa: F401
            engines.append(("laya", lambda fs: laya_score_all(states, args.model)))
        except ImportError:
            # eval 是对照实验，缺引擎时降级跑规则而不是直接退出，保证任何时候都能出基线
            print("[eval] 未安装 laya（pip install laya），本次只评估 heuristic 引擎")

    results = [evaluate_engine(feats, states, labels, kinds, fn, name, args.threshold)
               for name, fn in engines]

    print("\n" + "=" * 62)
    print(f"{'引擎':<12}{'准确率':>10}{'ECE':>10}{'缺陷归因准确率':>14}{'is_clean均值':>14}")
    for r in results:
        print(f"{r['engine']:<12}{r['accuracy']:>9.1%}{r['ece']:>10.3f}"
              f"{r['defect_accuracy']:>13.1%}{r['is_clean_mean']:>14.3f}")
    print("=" * 62)
    print("ECE = 期望校准误差（越小越可信：输出的置信度越接近真实正确率）。")
    print("注意：合成基准按规则阈值反向构造，天然偏向 heuristic；")
    print("      真实结论以 --labels 人工标注评估为准。")

    out_path = args.report or "laya_gate_eval.json"
    with open(out_path, "w", encoding="utf-8") as fp:
        json.dump({"results": results}, fp, ensure_ascii=False, indent=2)
    print(f"\n评估明细（含可靠性曲线数据）已写入 {out_path}")
    return results


# ----------------------------------------------------------------------
# 6. 主流程
# ----------------------------------------------------------------------

def build_windows(records, tub_path, window, stride, no_vision):
    """滑窗 + 特征提取。视觉特征只加载落在窗口内的帧，省 IO。"""
    starts = list(range(0, max(1, len(records) - window + 1), stride))
    needed = set()
    for s in starts:
        needed.update(r["_index"] for r in records[s:s + window])

    gray_by_index = {}
    if not no_vision:
        for rec in records:
            if rec["_index"] not in needed:
                continue
            g = load_gray(tub_path, rec)
            if g is not None:
                gray_by_index[rec["_index"]] = g
        print(f"      载入 {len(gray_by_index)} 帧灰度小图")

    feats_list, states = [], []
    for s in starts:
        win = records[s:s + window]
        if len(win) < window:
            break
        f = window_features(win, gray_by_index)
        f["n_frames"] = len(win)
        f["start"] = int(win[0]["_index"])
        f["end"] = int(win[-1]["_index"])
        # 记录该窗口覆盖的真实 _index 列表——不假设索引连续（删除过记录的 tub 有空洞）
        f["indices"] = [int(r["_index"]) for r in win]
        feats_list.append(f)
        states.append(render_state(f))
    return feats_list, states


def print_summary(feats_list, scores, keep, drop, balance):
    n = len(feats_list)
    print("\n" + "=" * 58)
    print(f"窗口总数        {n}")
    print(f"保留            {len(keep)}  ({len(keep)/max(n,1):.1%})")
    print(f"剔除            {len(drop)}  ({len(drop)/max(n,1):.1%})")
    print(f"is_clean 均值   {np.mean([s['is_clean'] for s in scores]):.3f}")
    print("\n缺陷归因:")
    for k, v in Counter(s["defect"] for s in scores).most_common():
        print(f"  {k:<18} {v:>6}  {v/n:6.1%}")
    print("\n机动分布:")
    for k, v in Counter(s["maneuver"] for s in scores).most_common():
        print(f"  {k:<18} {v:>6}  {v/n:6.1%}")
    if balance:
        kept_m = Counter(v["maneuver"] for v in keep)
        if kept_m:
            print("\n平衡后机动分布:")
            for k, v in kept_m.most_common():
                print(f"  {k:<18} {v:>6}  {v/max(len(keep),1):6.1%}")
    print("=" * 58)


def write_report(rep_path, feats_list, scores, keep, drop, engine):
    action_by_win = {d["win"]: d["action"] for d in drop}
    with open(rep_path, "w", encoding="utf-8") as fp:
        for i, (f, s) in enumerate(zip(feats_list, scores)):
            row = {k: v for k, v in f.items() if k not in ("n_frames", "indices")}
            row["indices"] = f["indices"]
            fp.write(json.dumps({**row, **s, "action": action_by_win.get(i, "keep"),
                                 "engine": engine}, ensure_ascii=False) + "\n")
    print(f"\n报告已写入 {rep_path}")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Donkeycar tub 离线数据质量阀门（Laya / 规则双引擎）")
    ap.add_argument("--tub", help="tub 目录（如 ~/mycar/data/tub_001）；eval+合成基准下可省略")
    ap.add_argument("--mode", default="report", choices=["report", "delete", "export", "eval"])
    ap.add_argument("--engine", default="heuristic", choices=["laya", "heuristic"],
                    help="默认 heuristic：合成基准实测 Laya 零样本仅为多数类基线"
                         "（准确率60%=干净占比，缺陷归因8%），见 README 实测记录；"
                         "标注数据拟合温度后可再用 --engine laya 复评")
    ap.add_argument("--model", default="convaiinnovations/laya",
                    help="convaiinnovations/laya | laya-multilingual | laya-typed-decisions")
    ap.add_argument("--window", type=int, default=10, help="窗口帧数，10 帧 ≈ 0.5s @20Hz")
    ap.add_argument("--stride", type=int, default=5, help="窗口步长")
    ap.add_argument("--threshold", type=float, default=0.35, help="is_clean 低于此值判坏")
    ap.add_argument("--balance", action="store_true", help="对直行窗口降采样做类别平衡")
    ap.add_argument("--straight-keep", type=float, default=0.5, help="直行窗口保留比例")
    ap.add_argument("--seed", type=int, default=0, help="降采样随机种子（可复现）")
    ap.add_argument("--no-vision", action="store_true", help="跳过视觉特征，只读遥测（快很多）")
    ap.add_argument("--out", help="export 模式的目标 tub 路径")
    ap.add_argument("--report", help="报告 jsonl / 评估 json 的输出路径")
    ap.add_argument("--labels", help="eval 模式：人工标注过的 report jsonl（含 label_clean）")
    ap.add_argument("--eval-windows", type=int, default=300, help="eval 合成基准窗口数")
    args = ap.parse_args(argv)

    if args.mode == "eval":
        run_eval(args)
        return

    if not args.tub:
        ap.error("--tub 是 report/delete/export 模式的必填参数")

    print(f"[1/5] 读取 tub: {args.tub}")
    records, inputs, types = load_tub_records(args.tub)
    print(f"      共 {len(records)} 条有效记录, inputs={inputs}")

    print("[2/5] 提取窗口特征")
    feats_list, states = build_windows(records, args.tub, args.window, args.stride,
                                       args.no_vision)
    if not feats_list:
        sys.exit(f"[x] 记录数不足一个窗口（window={args.window}）")
    print(f"      {len(feats_list)} 个窗口（window={args.window}, stride={args.stride}）")

    print(f"[3/5] 打分引擎: {args.engine}")
    if args.engine == "laya":
        scores = laya_score_all(states, args.model)
    else:
        scores = heuristic_score_all(feats_list)

    print("[4/5] 决策")
    keep, drop = decide(feats_list, scores, args.threshold,
                        args.balance, args.straight_keep, seed=args.seed)
    print_summary(feats_list, scores, keep, drop, args.balance)

    rep_path = args.report or os.path.join(args.tub, "laya_gate_report.jsonl")
    write_report(rep_path, feats_list, scores, keep, drop, args.engine)

    # 坏窗口覆盖的记录集合：用窗口携带的真实 _index 列表求并集，
    # 而不是 range(start, end+1)——删除过记录的 tub 索引有空洞，range 会误伤
    bad_idx = sorted({i for d in drop for i in d["indices"]})

    if args.mode == "report":
        print("\n[report 模式] 未改动任何数据。确认无误后再跑 delete / export。")
        return

    if args.mode == "delete":
        from donkeycar.parts.tub_v2 import Tub  # 官方接口，切勿手改 catalog 文件
        if not bad_idx:
            print("\n[delete 模式] 没有需要删除的记录，跳过。")
            return
        tub = Tub(args.tub)
        print(f"\n[delete 模式] 将软删除 {len(bad_idx)} 条记录（索引 {bad_idx[0]}..{bad_idx[-1]}）")
        tub.delete_records(bad_idx)
        tub.close()
        print("完成。delete_records 只做软标记，原图仍在磁盘上，可在 UI 里恢复。")

    elif args.mode == "export":
        if not args.out:
            sys.exit("[x] export 模式需要 --out")
        from donkeycar.parts.tub_v2 import Tub
        # inputs/types 优先用官方 Tub 从 manifest 读到的，读不到再用推断值
        try:
            src_probe = Tub(args.tub)
            inputs, types = src_probe.inputs or inputs, src_probe.types or types
            src_probe.close()
        except Exception:
            pass
        bad_set = set(bad_idx)
        dst = Tub(args.out, inputs=inputs, types=types)
        cnt, skipped = 0, 0
        for rec in records:
            if rec["_index"] in bad_set:
                continue
            img = load_rgb(args.tub, rec)
            if img is None:
                skipped += 1  # 图像缺失/损坏的记录导不出去，如实计数而不是静默丢
                continue
            new = {k: v for k, v in rec.items() if k not in META_KEYS}
            new["cam/image_array"] = img
            dst.write_record(new)
            cnt += 1
        dst.close()
        if skipped:
            print(f"\n[警告] {skipped} 条记录因图像缺失/损坏被跳过")
        print(f"[export 模式] 已导出 {cnt} 条到 {args.out}（原 tub 未动）")


if __name__ == "__main__":
    main()
