#!/usr/bin/env python3
"""make_eval_set.py —— 生成「固定输入集」，供 NPU / float32 参考反复对照。

用法:
    python3 make_eval_set.py --tub <tub 目录> --out-dir DIR [--frames 21] [--syn 5]

产出（写到 --out-dir）:
    sel.json   真实帧清单（去重后抽样；若 tub 带 catalog_manifest.json 则按真值分层）
    syn.npy    合成图（值域 0~1，能被输出推到两个符号，专治"单侧校准"）

为什么需要它：车载 tub 里重复帧很多（实测 787 帧里仅 272 帧唯一），直接取前 N 张会
让"连续帧输出相同"伪装成模型退化，也会让"测试集不合格"成为假象。
"""
import argparse
import glob
import hashlib
import json
import os

import numpy as np

SYN_SPECS = ("black", "white", "gray", "Lblack_Rwhite", "Lwhite_Rblack",
             "Tblack_Bwhite", "Twhite_Bblack", "ramp_h", "ramp_h_rev",
             "ramp_v", "ramp_v_rev")


def synth_images(names, size=(160, 120)):
    """按名字生成合成图（0~1 float32, HWC）。"""
    W, H = size
    z = np.zeros((H, W, 3), np.float32)
    o = np.ones((H, W, 3), np.float32)
    g = np.full((H, W, 3), 0.5, np.float32)
    rh = np.tile(np.linspace(0, 1, W, dtype=np.float32)[None, :, None], (H, 1, 3))
    rv = np.tile(np.linspace(0, 1, H, dtype=np.float32)[:, None, None], (1, W, 3))
    table = {
        "black": z, "white": o, "gray": g,
        "Lblack_Rwhite": np.concatenate([z[:, :W // 2], o[:, :W // 2]], axis=1),
        "Lwhite_Rblack": np.concatenate([o[:, :W // 2], z[:, :W // 2]], axis=1),
        "Tblack_Bwhite": np.concatenate([z[:H // 2], o[:H // 2]], axis=0),
        "Twhite_Bblack": np.concatenate([o[:H // 2], z[:H // 2]], axis=0),
        "ramp_h": rh, "ramp_h_rev": rh[:, ::-1].copy(),
        "ramp_v": rv, "ramp_v_rev": rv[::-1].copy(),
    }
    return [table[n] for n in names]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tub", required=True, help="tub 目录（读 images/，有 catalog_manifest.json 时用它取真值）")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--frames", type=int, default=21, help="真实帧数（去重后抽样）")
    ap.add_argument("--syn", type=int, default=5, help="合成图数量（<= %d）" % len(SYN_SPECS))
    ap.add_argument("--syn-names", default="", help="逗号分隔，覆盖默认合成图选择")
    a = ap.parse_args()

    os.makedirs(a.out_dir, exist_ok=True)
    imgs = sorted(glob.glob(os.path.join(a.tub, "images", "*.jpg")) +
                  glob.glob(os.path.join(a.tub, "images", "*.png")))
    seen, uniq = set(), []
    for f in imgs:
        h = hashlib.md5(open(f, "rb").read()).hexdigest()
        if h not in seen:
            seen.add(h)
            uniq.append(f)
    print("帧: 总 %d → 去重 %d（重复 %d）" % (len(imgs), len(uniq), len(imgs) - len(uniq)))

    truth = {}
    cat_path = os.path.join(a.tub, "catalog_manifest.json")
    if os.path.isfile(cat_path):
        try:
            for r in json.load(open(cat_path)):
                p = r.get("cam/image_array")
                if p:
                    truth[os.path.basename(p)] = (r.get("user/angle"), r.get("user/throttle"))
            print("真值: catalog 记录 %d 条" % len(truth))
        except Exception as e:
            print("真值: catalog 读取失败 %s: %s" % (type(e).__name__, e))
    else:
        print("真值: 无 catalog_manifest.json（只有图片的 tub）→ 仅作相对对照")

    withtruth = [(f, truth[os.path.basename(f)][0]) for f in uniq
                 if os.path.basename(f) in truth and truth[os.path.basename(f)][0] is not None]
    if len(withtruth) >= a.frames:
        withtruth.sort(key=lambda x: x[1])
        step = (len(withtruth) - 1) / (a.frames - 1)
        sel = [withtruth[int(round(i * step))] for i in range(a.frames)]
        print("抽样: 按真值分层 %d 帧，覆盖 %.3f .. %.3f" % (len(sel), sel[0][1], sel[-1][1]))
    else:
        step = max(1, len(uniq) // a.frames)
        sel = [(f, None) for f in uniq[::step][:a.frames]]
        print("抽样: 均匀 %d 帧（无真值）" % len(sel))

    names = [n.strip() for n in a.syn_names.split(",") if n.strip()] or list(SYN_SPECS[:a.syn])
    names = names[:a.syn]
    syn = synth_images(names)

    json.dump({"tub": os.path.abspath(a.tub),
               "frames": [{"path": f, "angle": ang} for f, ang in sel],
               "syn_names": names},
              open(os.path.join(a.out_dir, "sel.json"), "w"), indent=1)
    np.save(os.path.join(a.out_dir, "syn.npy"), np.stack(syn))
    print("已写 %s/{sel.json,syn.npy}  合成图: %s" % (a.out_dir, ",".join(names)))


if __name__ == "__main__":
    main()
