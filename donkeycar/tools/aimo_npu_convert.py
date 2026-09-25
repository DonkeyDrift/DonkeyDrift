#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AIMO 云转换：onnx → QCS6490(QNN 2.40) .aidem NPU 模型。

移植自 ~/tools/aimo_convert.py（实测过的坑都保留）：
  * 创建任务与提交必须在同一进程内完成，否则 TaskNotExistError；
  * 状态字段是 ResultTaskInfo.task_status；
  * 量化 cle 快（Sim01 级别 ~25s）、ada 可能极慢；
  * 校准集用任务相关图片（tub 帧）优于内置 ImageNet/COCO；
  * API Key 从文件读，绝不出现在命令行。

车端用法：.aidem + 同目录 qnn_model_info.json → 模型类型 aidlite_linear
（donkeycar/parts/npu_pilot.py，TYPE_QNN240+TYPE_DSP）。

CLI:
    python3 -m donkeycar.tools.aimo_npu_convert --onnx model.onnx [--out 目录]
        [--calib-tubs tub1,tub2] [--calib-max 100] [--timeout 3600]
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from typing import Optional

KEY_FILE = os.environ.get("AIMO_KEY_FILE", "/home/aidlux/.aidlux_cred/aimo_api_key")

DEVICE = "Qualcomm_QCS6490"
RUNTIME = "qnn_2_40"


def _collect_calib_images(tub_paths: str, max_images: int = 100,
                          tmp_parent: str = "/tmp") -> Optional[str]:
    """从 tub 的 images/ 目录取前 N 张图，软链到临时目录供上传。取不到返回 None。"""
    files = []
    for tub in tub_paths.split(','):
        img_dir = os.path.join(os.path.expanduser(tub), 'images')
        if os.path.isdir(img_dir):
            files.extend(os.path.join(img_dir, f)
                         for f in sorted(os.listdir(img_dir))
                         if f.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp')))
    files = files[:max_images]
    if not files:
        return None
    calib_dir = tempfile.mkdtemp(prefix='aimo_calib_', dir=tmp_parent)
    for i, src in enumerate(files):
        ext = os.path.splitext(src)[1]
        os.symlink(os.path.abspath(src), os.path.join(calib_dir, f"calib_{i:04d}{ext}"))
    print(f"      校准图 {len(files)} 张（来自 tub）")
    return calib_dir


def convert_onnx_to_aidem(onnx_path: str, out_dir: str,
                          calib_tub_paths: Optional[str] = None,
                          calib_max: int = 100, timeout_s: int = 3600,
                          poll_s: int = 15,
                          precision: str = "INT8") -> Optional[str]:
    """转换并下载产物；返回 .aidem 路径，失败返回 None。"""
    from aplux_aimo import AimoApi
    from aplux_aimo.enums import (SourceModelType, TargetDevice, ModelRuntime,
                                  ModelDataPrecision, DownloadFileMode)
    from aplux_aimo.base_data import QuantizeOptions

    onnx_path = os.path.abspath(onnx_path)
    if not os.path.isfile(onnx_path):
        print(f"源模型不存在: {onnx_path}")
        return None
    if not os.path.isfile(KEY_FILE):
        print(f"未找到 API Key 文件: {KEY_FILE}（可用环境变量 AIMO_KEY_FILE 指定）")
        return None
    api_key = open(KEY_FILE).read().strip()

    aimo = AimoApi()
    aimo.login(api_key=api_key)
    print(f"[1/5] AIMO 登录成功")

    quant = QuantizeOptions(
        quantize_precision=getattr(ModelDataPrecision, precision),
        quantize_mode=["cle"],
        enable_per_channel_quantize=True,
        calibration_data_mode="cv",
        calibration_dataset_type="custom" if calib_tub_paths else "imagenet",
    )
    task = aimo.new_task(
        source_model_type=SourceModelType.ONNX,
        source_model_file=onnx_path,
        target_device=TargetDevice.Qualcomm_QCS6490,
        target_runtime=ModelRuntime.QNN_2_40,
        description=f"donkeycar torch-linear {os.path.basename(onnx_path)}",
        quantize_options=quant,
    )
    print(f"[2/5] 任务已创建: {task.task_id} "
          f"({os.path.getsize(onnx_path)} B → {DEVICE}/{RUNTIME} {precision})")

    if calib_tub_paths:
        calib_dir = _collect_calib_images(calib_tub_paths, calib_max)
        if calib_dir:
            files = [os.path.join(calib_dir, f) for f in sorted(os.listdir(calib_dir))]
            task.upload_calibration_data_files(files=files)

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
    got = task.download(file_mode=DownloadFileMode.OutputModel, output_file_path=out_dir)
    print(f"[5/5] 已下载到: {got}")
    print("      车端用 *.ctx.bin.aidem + 同目录 qnn_model_info.json "
          "（模型类型 aidlite_linear）")
    return got


def main():
    p = argparse.ArgumentParser(description="onnx → QCS6490 .aidem (AIMO 云转)")
    p.add_argument("--onnx", required=True)
    p.add_argument("--out", default=".")
    p.add_argument("--calib-tubs", default="", help="逗号分隔 tub 路径，取 images/ 前 N 张做校准")
    p.add_argument("--calib-max", type=int, default=100)
    p.add_argument("--timeout", type=int, default=3600)
    a = p.parse_args()
    ret = convert_onnx_to_aidem(a.onnx, a.out, a.calib_tubs or None,
                                a.calib_max, a.timeout)
    sys.exit(0 if ret else 1)


if __name__ == "__main__":
    main()
