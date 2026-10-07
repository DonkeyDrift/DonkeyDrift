#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AIMO 云转换：onnx → QCS6490(QNN 2.40) .aidem NPU 模型。

移植自 ~/tools/aimo_convert.py（实测过的坑都保留）：
  * 创建任务与提交必须在同一进程内完成，否则 TaskNotExistError；
  * 状态字段是 ResultTaskInfo.task_status；
  * 量化 cle 快（Sim01 级别 ~25s）、ada 可能极慢；
  * 校准集用任务相关图片（tub 帧）优于内置 ImageNet/COCO；
  * API Key 只从环境变量读取（AIMO_API_KEY 值式 / AIMO_KEY_FILE 文件路径），绝不入库、不出现在命令行。

车端用法：.aidem + 同目录 qnn_model_info.json → 模型类型 aidlite_linear
（donkeycar/parts/npu_pilot.py，TYPE_QNN240+TYPE_DSP）。

源模型: .onnx / .tflite / .pb(frozen) / .pt,.pth(PyTorch) / saved_model 目录（类型自动识别）

CLI:
    python3 -m donkeycar.tools.aimo_npu_convert --onnx model.onnx [--out 目录]
        [--calib-tubs tub1,tub2] [--calib-max 100] [--timeout 3600]

环境变量:
    AIMO_API_KEY   AIMO API Key 值（首选；不入库、不落盘）
    AIMO_KEY_FILE  密钥文件路径（备选，默认 ~/.aidlux_cred/aimo_api_key）
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
from typing import Optional
import glob

KEY_ENV_VAR = "AIMO_API_KEY"        # 首选：环境变量直接给 key 值（不入库、不落盘）
KEY_FILE_ENV_VAR = "AIMO_KEY_FILE"  # 备选：环境变量指向密钥文件
DEFAULT_KEY_FILE = os.path.expanduser("~/.aidlux_cred/aimo_api_key")

# 兼容旧引用；实际取值一律走 load_api_key()
KEY_FILE = os.environ.get(KEY_FILE_ENV_VAR, DEFAULT_KEY_FILE)


def load_api_key() -> Optional[str]:
    """读取 AIMO API Key。优先级：AIMO_API_KEY(值) > AIMO_KEY_FILE(文件) > ~/.aidlux_cred/aimo_api_key。

    key 只从环境变量 / 本机凭据文件读取，绝不写入仓库；返回值仅用于登录，不打印、不落日志。
    """
    val = (os.environ.get(KEY_ENV_VAR) or "").strip()
    if val:
        return val
    for path in (os.environ.get(KEY_FILE_ENV_VAR) or "", DEFAULT_KEY_FILE):
        if path and os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    val = fh.read().strip()
            except OSError:
                continue
            if val:
                return val
    return None

# 源模型类型推断（值 = AIMO 的 SourceModelType 枚举名）
SRC_TYPE_BY_EXT = {
    ".onnx": "ONNX",
    ".tflite": "TensorFlow_Lite",
    ".pb": "TensorFlow_PB",
    ".pt": "PyTorch",
    ".pth": "PyTorch",
    ".caffemodel": "Caffe",
    ".mxnet": "MXNet",
    ".pdmodel": "PaddlePaddle",
    ".pdiparams": "PaddlePaddle",
}

# 内置校准集名字 -> CalibrationDatasetType 成员名（注意大小写）
CALIB_DATASET_MEMBER = {"imagenet": "ImageNet", "coco": "COCO",
                        "face": "Face", "normal": "Normal"}


# 合成校准图：刻意让输出覆盖**双侧**（见 docs/npu/AIMO量化校准-单侧校准陷阱.md）。
# 只喂真实 tub 帧时，若参考输出恰好是单侧的（如 steering 全为负），AIMO 会按该单侧范围
# 给输出张量定标 → 反号的值被压到零点（读出来恒 0）。混入这些图即可把范围拉回双侧。
SYNTH_SPECS = ("black", "white", "gray", "Lblack_Rwhite", "Lwhite_Rblack",
               "Tblack_Bwhite", "Twhite_Bblack", "ramp_h", "ramp_h_rev",
               "ramp_v", "ramp_v_rev", "noise")


def _make_synth_images(out_dir: str, count: int, size=(160, 120)) -> int:
    """生成 count 张合成图到 out_dir，返回实际生成数。循环使用 SYNTH_SPECS。"""
    if count <= 0:
        return 0
    import numpy as np
    W, H = size
    z = np.zeros((H, W, 3), np.uint8)
    o = np.full((H, W, 3), 255, np.uint8)
    g = np.full((H, W, 3), 128, np.uint8)
    ramp_h = np.tile(np.linspace(0, 255, W, dtype=np.uint8)[None, :, None], (H, 1, 3))
    ramp_v = np.tile(np.linspace(0, 255, H, dtype=np.uint8)[:, None, None], (1, W, 3))
    rng = np.random.RandomState(0)
    made = 0
    try:
        import cv2
    except ImportError:
        cv2 = None
    for i in range(count):
        k = SYNTH_SPECS[i % len(SYNTH_SPECS)]
        if k == "black":
            img = z
        elif k == "white":
            img = o
        elif k == "gray":
            img = g
        elif k == "Lblack_Rwhite":
            img = np.concatenate([z[:, :W // 2], o[:, :W // 2]], axis=1)
        elif k == "Lwhite_Rblack":
            img = np.concatenate([o[:, :W // 2], z[:, :W // 2]], axis=1)
        elif k == "Tblack_Bwhite":
            img = np.concatenate([z[:H // 2], o[:H // 2]], axis=0)
        elif k == "Twhite_Bblack":
            img = np.concatenate([o[:H // 2], z[:H // 2]], axis=0)
        elif k == "ramp_h":
            img = ramp_h
        elif k == "ramp_h_rev":
            img = ramp_h[:, ::-1].copy()
        elif k == "ramp_v":
            img = ramp_v
        elif k == "ramp_v_rev":
            img = ramp_v[::-1].copy()
        else:
            img = rng.randint(0, 256, (H, W, 3), dtype=np.uint8)
        name = os.path.join(out_dir, "synth_%02d_%s" % (i, k))
        if cv2 is not None:
            cv2.imwrite(name + ".jpg", img)
        else:
            from PIL import Image
            Image.fromarray(img[:, :, ::-1]).save(name + ".png")
        made += 1
    return made


def resolve_source_type(model_path: str, override: str = "") -> str:
    """推断 AIMO 的源模型类型枚举名；override 非空时直接用它。

    支持 .onnx / .tflite / .pb(frozen) / .pt,.pth(PyTorch) / 含 saved_model.pb 的目录。
    """
    if override:
        return override
    low = str(model_path).lower()
    if low.endswith(".tflite"):
        return "TensorFlow_Lite"
    if os.path.isdir(model_path):
        if os.path.isfile(os.path.join(model_path, "saved_model.pb")):
            return "TensorFlow_Save_Model"
        raise ValueError(f"目录 {model_path} 不是 saved_model（缺 saved_model.pb）")
    ext = os.path.splitext(low)[1]
    if ext in SRC_TYPE_BY_EXT:
        return SRC_TYPE_BY_EXT[ext]
    raise ValueError(f"无法从 {model_path} 推断源模型类型，请用 source_type= 显式指定")


DEVICE = "Qualcomm_QCS6490"
RUNTIME = "qnn_2_40"


def _collect_calib_images(tub_paths: str, max_images: int = 100,
                          tmp_parent: str = "/tmp", mix_synth: int = 0) -> Optional[str]:
    """从 tub 的 images/ 目录取前 N 张图，软链到临时目录供上传。取不到返回 None。"""
    files = []
    for tub in tub_paths.split(','):
        img_dir = os.path.join(os.path.expanduser(tub), 'images')
        if os.path.isdir(img_dir):
            files.extend(os.path.join(img_dir, f)
                         for f in sorted(os.listdir(img_dir))
                         if f.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp')))
    synth = max(0, min(int(mix_synth or 0), max_images - 1)) if max_images > 1 else 0
    files = files[:max_images - synth]
    if not files and not synth:
        return None
    calib_dir = tempfile.mkdtemp(prefix='aimo_calib_', dir=tmp_parent)
    for i, src in enumerate(files):
        ext = os.path.splitext(src)[1]
        # 真实拷贝而非软链：AIMO SDK 上传时不跟随符号链接
        shutil.copy2(os.path.abspath(src), os.path.join(calib_dir, f"calib_{i:04d}{ext}"))
    if synth:
        n = _make_synth_images(calib_dir, synth)
        print(f"      校准集混入合成图 {n} 张（覆盖输出双侧，避免单侧校准截断输出头）")
    print(f"      校准图 {len(files)} 张（来自 tub）")
    return calib_dir


def _unpack_zips(out_dir: str, got=None) -> list:
    """解包 AIMO 下载产物，返回解出的文件名列表（basename）。

    ⚠ `task.download()` 返回的是**列表**（实测 `['/…/xxx_save_path.zip']`），不是字符串 ——
    只判 `isinstance(got, str)` 会「下载成功但不解包」，脚本随后报"找不到 ctx"，
    而 AIMO 额度已经花掉了。本函数同时兼容 list / str / 空（空则在 out_dir 里扫 zip 自愈）。
    """
    import zipfile

    cands = []
    for p in (got if isinstance(got, (list, tuple)) else ([got] if got else [])):
        if p and os.path.isfile(p):
            cands.append(p)
    if not cands:
        cands = sorted(glob.glob(os.path.join(out_dir, "*save_path*.zip"))
                       or glob.glob(os.path.join(out_dir, "*.zip")))
    names = []
    for p in cands:
        if not zipfile.is_zipfile(p):
            names.append(os.path.basename(p))
            continue
        with zipfile.ZipFile(p) as z:
            z.extractall(out_dir)
            members = [m for m in z.namelist() if not m.endswith("/")]
        names.extend(os.path.basename(m) for m in members)
        print(f"      已解包 {os.path.basename(p)} → {len(members)} 个文件")
    return names


def convert_onnx_to_aidem(onnx_path: str, out_dir: str,
                          calib_tub_paths: Optional[str] = None,
                          calib_max: int = 100, timeout_s: int = 3600,
                          poll_s: int = 15,
                          precision: str = "INT8",
                          source_type: str = "",
                          calib_dataset: str = "imagenet",
                          calib_mix_synth: int = 0) -> Optional[str]:
    """转换并下载产物；返回 .aidem 路径，失败返回 None。

    形参名沿用 onnx_path 仅为兼容既有调用；实际支持多种源模型
    （.onnx / .tflite / .pb / .pt,.pth / saved_model 目录），类型自动识别，
    也可用 source_type 显式指定 SourceModelType 枚举名。
    calib_dataset: 无校准 tub 时使用的内置校准集（imagenet/coco/face/normal）。
    """
    from aplux_aimo import AimoApi
    from aplux_aimo.enums import (SourceModelType, TargetDevice, ModelRuntime,
                                  ModelDataPrecision, DownloadFileMode,
                                  CalibrationDataMode, CalibrationDatasetType)
    from aplux_aimo.base_data import QuantizeOptions

    onnx_path = os.path.abspath(onnx_path)
    if not os.path.exists(onnx_path):
        print(f"源模型不存在: {onnx_path}")
        return None
    try:
        src_type = resolve_source_type(onnx_path, source_type)
    except ValueError as exc:
        print(f"源模型类型无法确定: {exc}")
        return None
    if not hasattr(SourceModelType, src_type):
        print(f"SourceModelType 无成员 {src_type}；可选 "
              f"{[x for x in dir(SourceModelType) if not x.startswith('_')]}")
        return None
    print(f"[0/5] 源模型类型: SourceModelType.{src_type}  ({os.path.basename(onnx_path)})")
    api_key = load_api_key()
    if not api_key:
        print(f"未找到 AIMO API Key：请设置环境变量 {KEY_ENV_VAR}=<key>"
              f"（备选 {KEY_FILE_ENV_VAR}=<密钥文件路径>，默认 {DEFAULT_KEY_FILE}）")
        return None

    aimo = AimoApi()
    aimo.login(api_key=api_key)
    print(f"[1/5] AIMO 登录成功")

    # 按精度组装量化参数：FP16 是纯 fp16，不与 INT8 专用的
    # quantize_mode / per-channel 选项混用（服务端会报 unsupported mix precision）
    q_kwargs = {
        "quantize_precision": getattr(ModelDataPrecision, precision),
        # 必须传 SDK 枚举成员：CalibrationDatasetType.Custom 的值是空字符串 '',
        # 传字面量 "custom" 会让 SDK 的上传守卫条件不成立而静默跳过校准集
        "calibration_data_mode": CalibrationDataMode.Image,
        "calibration_dataset_type": (CalibrationDatasetType.Custom if calib_tub_paths
                                     else getattr(CalibrationDatasetType,
                                                  CALIB_DATASET_MEMBER.get(
                                                      (calib_dataset or "imagenet").lower(),
                                                      "ImageNet"))),
    }
    if precision.upper() != "FP16":
        q_kwargs["quantize_mode"] = ["cle"]
        q_kwargs["enable_per_channel_quantize"] = True
    quant = QuantizeOptions(**q_kwargs)
    task = aimo.new_task(
        source_model_type=getattr(SourceModelType, src_type),
        source_model_file=onnx_path,
        target_device=TargetDevice.Qualcomm_QCS6490,
        target_runtime=ModelRuntime.QNN_2_40,
        description=f"donkeycar torch-linear {os.path.basename(onnx_path)}",
        quantize_options=quant,
    )
    print(f"[2/5] 任务已创建: {task.task_id} "
          f"({os.path.getsize(onnx_path)} B → {DEVICE}/{RUNTIME} {precision})")

    if calib_tub_paths:
        calib_dir = _collect_calib_images(calib_tub_paths, calib_max, mix_synth=calib_mix_synth)
        if not calib_dir:
            print("      未从 tub 取到图片，改用内置校准集")
        else:
            files = [os.path.join(calib_dir, f) for f in sorted(os.listdir(calib_dir))]
            try:
                task.upload_calibration_data_files(files=files)
            except Exception as exc:
                print(f"      校准集上传异常: {type(exc).__name__}: {exc}")
            got = getattr(task.config.quantize_options, "calibration_data_files", None) or []
            if got:
                print(f"[2.5/5] 校准集已上传: {len(files)} 张 -> {len(got)} 个 URL")
            else:
                print(f"      !! 校准集上传被跳过（{len(files)} 张未生效）："
                      f"mode/dataset 必须是 SDK 枚举成员")

    task.submit()
    print(f"[3/5] 已提交，轮询中（间隔 {poll_s}s，上限 {timeout_s}s）...")
    t0, final = time.time(), None
    while time.time() - t0 < timeout_s:
        try:
            info = task.get_result()
            st = str(getattr(info, "task_status", ""))
            if final != st:
                print(f"      [{int(time.time()-t0):4d}s] {st}  "
                      f"{str(getattr(info, 'message', ''))[:120]}")
                final = st
            if "SUCCESS" in st.upper() or "FAIL" in st.upper() or "ERROR" in st.upper():
                break
        except Exception as e:
            print(f"      [{int(time.time()-t0):4d}s] 查询异常 "
                  f"{type(e).__name__}: {str(e)[:120]}")
        time.sleep(poll_s)

    print(f"[4/5] 终态: {final}  (task_id={task.task_id})")
    if not (final and "SUCCESS" in final.upper()):
        try:
            print(str(task.get_info_log())[:3000])
        except Exception as e:
            print("  日志获取失败:", e)
        return None

    os.makedirs(out_dir, exist_ok=True)
    # 自愈：先把上次「下载成功但没解包」的产物解出来（AIMO 额度宝贵，别为本地解包 bug 重转）
    _unpack_zips(out_dir)
    got = task.download(file_mode=DownloadFileMode.OutputModel, output_file_path=out_dir)
    print(f"[5/5] 已下载到: {got}")
    arts = _unpack_zips(out_dir, got)
    aidem = [a for a in arts if a.endswith(".aidem") and "x86" not in a]
    if aidem:
        print(f"      ★ 车端模型: {aidem[0]}")
        print("      ★ 与同目录的 qnn_model_info.json 必须一起拷贝上车")
    else:
        print(f"      ! 未解出 *.ctx.bin.aidem，请检查 {out_dir}")
    if any("x86" in a for a in arts):
        print("      ! 产物含 x86 仿真库 lib*.x86.so.aidem —— 仅 PC 仿真用，别拷到车上")
    if any(a.endswith("qnn_model_info.json") for a in arts):
        print("      ★ 推理时形状从 qnn_model_info.json 读，缺了会静默出 NaN")
    return got


def main():
    p = argparse.ArgumentParser(description="onnx → QCS6490 .aidem (AIMO 云转)")
    p.add_argument("--onnx", required=True)
    p.add_argument("--out", default=".")
    p.add_argument("--calib-tubs", default="", help="逗号分隔 tub 路径，取 images/ 前 N 张做校准")
    p.add_argument("--calib-max", type=int, default=100)
    p.add_argument("--precision", default="INT8", choices=["INT8", "INT16", "FP16"],
                   help="AIMO 量化精度: INT8(A8_W8) / INT16(A16_W8) / FP16(Afp16_Wfp16)")
    p.add_argument("--calib-mix-synth", type=int, default=0,
                   help="校准集里混入多少张合成图（强烈建议 >=30）：只喂真实帧时若参考输出单侧，\n                         AIMO 会按单侧范围定标 → 反号输出被截成 0（见 docs/npu/AIMO量化校准-单侧校准陷阱.md）")
    p.add_argument("--calib-dataset", default="imagenet",
                   help="无 --calib-tubs 时使用的内置校准集: imagenet/coco/face/normal")
    p.add_argument("--timeout", type=int, default=3600)
    a = p.parse_args()
    ret = convert_onnx_to_aidem(a.onnx, a.out, a.calib_tubs or None,
                                a.calib_max, a.timeout,
                                precision=a.precision,
                                calib_dataset=a.calib_dataset,
                                calib_mix_synth=a.calib_mix_synth)
    sys.exit(0 if ret else 1)


if __name__ == "__main__":
    main()
