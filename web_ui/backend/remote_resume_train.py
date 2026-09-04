#!/usr/bin/env python3
"""远程断点续训脚本（由 WebOnlineTrainer.run_resume 上传到远程车目录执行）。

远程 train.py 模板不支持 --transfer；本脚本直接调 donkeydrifter pipeline 的
train(cfg, tub, model, model_type, transfer, comment)，加载上次训练留下的
最优权重，复用远程已上传的同一份数据接着练（epoch 重新从 1 开始，
early stopping 照常）。
"""
import argparse
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL', '2')

# 执行远程车目录里 train.py 的 GPU 显存/混合精度前导配置，
# 保证续训环境与首发训练一致
import train as _car_train  # noqa: F401

import donkeydrifter as dk
from donkeydrifter.pipeline.training import train as pipeline_train


def main():
    parser = argparse.ArgumentParser(description="DonkeyDrift 远程断点续训")
    parser.add_argument("--tub", required=True, help="训练数据目录（相对车目录）")
    parser.add_argument("--model", required=True, help="新模型输出路径")
    parser.add_argument("--type", default="linear", help="模型类型（默认 linear）")
    parser.add_argument("--transfer", required=True, help="上次训练留下的最优权重路径")
    args = parser.parse_args()

    if "transfer" not in inspect.signature(pipeline_train).parameters:
        print("远程 donkeydrifter 版本过旧，不支持断点续训，请使用「开始训练」重新训练",
              file=sys.stderr)
        sys.exit(2)

    cfg = dk.load_config()
    pipeline_train(cfg, args.tub, args.model, args.type, args.transfer, None)


if __name__ == "__main__":
    main()
