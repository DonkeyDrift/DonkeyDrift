#!/usr/bin/env python3
"""npu_eval.py <model.ctx.bin.aidem> <out.json> [--set-dir DIR] [--input-scale div255|raw]

在固定输入集上跑 NPU（aidlite，TYPE_QNN240 + TYPE_DSP）。
默认 --input-scale div255：AIMO 转换产物的图像约定是 /255（与源模型自身的尺度无关）。
"""
import argparse
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
import numpy as np
import cv2
import aidlite


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("out")
    ap.add_argument("--set-dir", default="eval_set")
    ap.add_argument("--input-scale", choices=["div255", "raw"], default="div255")
    a = ap.parse_args()

    sel = json.load(open(os.path.join(a.set_dir, "sel.json")))
    syn = np.load(os.path.join(a.set_dir, "syn.npy"))          # 0~1
    info = json.load(open(os.path.join(os.path.dirname(os.path.abspath(a.model)),
                                       "qnn_model_info.json")))
    inp, ot = info["inputDimensions"], info["outputDimensions"]
    m = aidlite.Model.create_instance(a.model)
    m.set_model_properties(list(inp.values()), aidlite.DataType.TYPE_FLOAT32,
                           list(ot.values()), aidlite.DataType.TYPE_FLOAT32)
    c = aidlite.Config.create_instance()
    c.framework_type = aidlite.FrameworkType.TYPE_QNN240
    c.accelerate_type = aidlite.AccelerateType.TYPE_DSP
    it = aidlite.InterpreterBuilder.build_interpreter_from_model_and_config(m, c)
    if it is None or it.init() != 0 or it.load_model() != 0:
        sys.exit("  ✗ 模型初始化失败: %s" % a.model)

    def run(x):
        it.set_input_tensor(0, np.ascontiguousarray(x[None, ...], dtype=np.float32))
        it.invoke()
        return [float(np.asarray(it.get_output_tensor(i)).reshape(-1)[0]) for i in range(len(ot))]

    hw = (list(inp.values())[0][1], list(inp.values())[0][2])
    real = []
    for fr in sel["frames"]:
        img = cv2.cvtColor(cv2.resize(cv2.imread(fr["path"]), (hw[1], hw[0])), cv2.COLOR_BGR2RGB).astype(np.float32)
        real.append(run(img / 255.0 if a.input_scale == "div255" else img))
    out = {"model": os.path.abspath(a.model), "input_scale": a.input_scale,
           "syn_names": sel.get("syn_names", []), "real": real,
           "syn": [run(s.astype(np.float32) * (255.0 if a.input_scale == "raw" else 1.0)) for s in syn]}
    json.dump(out, open(a.out, "w"))
    print("  ✓ %s（real=%d syn=%d, scale=%s）" % (a.out, len(real), len(out["syn"]), a.input_scale))


if __name__ == "__main__":
    main()
