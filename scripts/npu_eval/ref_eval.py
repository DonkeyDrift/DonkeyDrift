#!/usr/bin/env python3
"""ref_eval.py <model.tflite> <out.json> [--set-dir DIR] [--input-scale raw|div255] [--car-dir DIR]

用工程自带的 TFLite 解释器跑 float32 参考（与 NPU 同一批输入）。
--input-scale 必须跟**源模型自身**的尺度走：可以用行为判据确认 ——
喂 0~255 与 /255 两种尺度，哪个对极端图像（黑/白）敏感（输出变化 >0.1）就是它训练时的等效尺度。
"""
import argparse
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
import numpy as np
import cv2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("out")
    ap.add_argument("--set-dir", default="eval_set")
    ap.add_argument("--input-scale", choices=["raw", "div255"], default="raw")
    ap.add_argument("--car-dir", default=".", help="含 config.py 的车目录（load_config 需要）")
    a = ap.parse_args()

    # 注意：必须在 chdir 之前把模型路径解析成绝对路径（否则相对路径会落到车目录里）
    model_abs = os.path.abspath(os.path.expanduser(a.model))
    if not os.path.isfile(model_abs):
        sys.exit("  ✗ 找不到源模型: %s" % model_abs)
    os.chdir(os.path.expanduser(a.car_dir))
    import donkeycar as dk
    from donkeycar.utils import get_model_by_type
    cfg = dk.load_config()
    p = get_model_by_type("tflite_linear", cfg)
    p.load(model_abs)

    sel = json.load(open(os.path.join(a.set_dir, "sel.json")))
    syn = np.load(os.path.join(a.set_dir, "syn.npy")) * (1.0 if a.input_scale == "div255" else 255.0)
    real = []
    for fr in sel["frames"]:
        img = cv2.cvtColor(cv2.resize(cv2.imread(fr["path"]), (160, 120)), cv2.COLOR_BGR2RGB).astype(np.float32)
        if a.input_scale == "div255":
            img = img / 255.0
        real.append([float(t) for t in np.asarray(p.run(img)).reshape(-1)])
    out = {"model": a.model, "input_scale": a.input_scale, "syn_names": sel.get("syn_names", []),
           "real": real, "syn": [[float(t) for t in np.asarray(p.run(s)).reshape(-1)] for s in syn]}
    json.dump(out, open(a.out, "w"))
    print("  ✓ %s（real=%d syn=%d, scale=%s）" % (a.out, len(real), len(out["syn"]), a.input_scale))


if __name__ == "__main__":
    main()
