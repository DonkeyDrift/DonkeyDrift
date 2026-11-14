# -*- coding: utf-8 -*-
"""aimo_npu_convert 产物解包：AIMO 下载的 zip 自动解压为自包含模型目录。"""
import os
import zipfile

import pytest

from donkeycar.tools.aimo_npu_convert import _unpack_if_archive


def _make_zip(path, entries):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)


def test_zip_extracted_to_selfcontained_dir_ctx_bin_preferred(tmp_path):
    out_dir = tmp_path / "models"
    out_dir.mkdir()
    zip_path = out_dir / "pilot_save_path.zip"
    _make_zip(str(zip_path), {
        "pilot_qcs6490_w8a8.qnn240.ctx.bin.aidem": b"ctx",
        "libpilot_qcs6490_w8a8.qnn240.x86.so.aidem": b"x86",
        "qnn_model_info.json": b"{}",
        "htp_config.json": b"{}",
    })

    got = _unpack_if_archive(str(zip_path), str(out_dir))

    # 车端模型 = 子目录里的 *.ctx.bin.aidem（不是 x86 模拟器变体）
    target = out_dir / "pilot_save_path"
    assert got == str(target / "pilot_qcs6490_w8a8.qnn240.ctx.bin.aidem")
    assert os.path.isfile(got)
    # npu_pilot 要求 qnn_model_info.json 与 .aidem 同目录
    assert (target / "qnn_model_info.json").is_file()
    # zip 校验落地后清理
    assert not zip_path.exists()


def test_zip_without_ctx_bin_falls_back_to_any_aidem(tmp_path):
    out_dir = tmp_path / "models"
    out_dir.mkdir()
    zip_path = out_dir / "m.zip"
    _make_zip(str(zip_path), {
        "m.aidem": b"model",
        "qnn_model_info.json": b"{}",
    })

    got = _unpack_if_archive(str(zip_path), str(out_dir))

    assert got == str(out_dir / "m" / "m.aidem")


def test_zip_without_aidem_returns_target_dir(tmp_path):
    out_dir = tmp_path / "models"
    out_dir.mkdir()
    zip_path = out_dir / "m.zip"
    _make_zip(str(zip_path), {"readme.txt": b"hi"})

    got = _unpack_if_archive(str(zip_path), str(out_dir))

    assert got == str(out_dir / "m")
    assert (out_dir / "m" / "readme.txt").is_file()


def test_non_zip_file_returned_as_is(tmp_path):
    out_dir = tmp_path / "models"
    out_dir.mkdir()
    bare = out_dir / "m.qnn240.ctx.bin.aidem"
    bare.write_bytes(b"raw model")

    assert _unpack_if_archive(str(bare), str(out_dir)) == str(bare)
    assert bare.is_file()


def test_zip_slip_rejected(tmp_path):
    out_dir = tmp_path / "models"
    out_dir.mkdir()
    zip_path = out_dir / "evil.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("../evil.aidem", b"bad")

    with pytest.raises(ValueError):
        _unpack_if_archive(str(zip_path), str(out_dir))

    # 未落地任何越界文件
    assert not (tmp_path / "evil.aidem").exists()
