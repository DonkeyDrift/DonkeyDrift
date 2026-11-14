#!/usr/bin/env python3
"""cmp_eval.py <ref.json> <npu1.json> [npu2.json ...]

逐头统计（平均/最大 |Δ|、非零帧数）+ 合成输入逐项对照。
回归/标量输出模型**不要**用余弦相似度：单元素向量会因符号翻转误报 -1，逐值对照才是对的。
"""
import json
import sys

import numpy as np


def main():
    ref = json.load(open(sys.argv[1]))
    models = [(sys.argv[i].split("/")[-1].replace(".json", ""), json.load(open(sys.argv[i])))
              for i in range(2, len(sys.argv))]
    r = np.array(ref["real"])
    print("── 真实帧（%d）──" % len(r))
    print("  %-24s %-34s %s" % ("模型", "steering 平均|Δ| / 最大|Δ|（非零）", "throttle 平均|Δ| / 最大|Δ|（非零）"))
    for nm, d in models:
        a = np.array(d["real"])
        ds, dt = np.abs(a[:, 0] - r[:, 0]), np.abs(a[:, 1] - r[:, 1])
        print("  %-24s %8.4f / %8.4f (%2d/%d)      %8.4f / %8.4f (%2d/%d)"
              % (nm, ds.mean(), ds.max(), int((a[:, 0] != 0).sum()), len(a),
                 dt.mean(), dt.max(), int((a[:, 1] != 0).sum()), len(a)))
    rs = np.array(ref["syn"])
    names = ref.get("syn_names") or ["syn%d" % i for i in range(len(rs))]
    print("\n── 合成输入（推两个符号，用来看输出头是否被单侧截断）──")
    print("  %-14s %-20s %s" % ("输入", "参考 steer/throt", "  ".join("%-22s" % nm for nm, _ in models)))
    for i, k in enumerate(names):
        cells = "  ".join("%+8.4f/%+8.4f" % (np.array(d["syn"])[i, 0], np.array(d["syn"])[i, 1])
                          for _, d in models)
        print("  %-14s %+8.4f/%+8.4f   %s" % (k, rs[i, 0], rs[i, 1], cells))


if __name__ == "__main__":
    main()
