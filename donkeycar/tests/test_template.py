# -*- coding: utf-8 -*-

from tempfile import gettempdir
from donkeycar.templates import complete
import donkeycar as dk
import os
from pathlib import Path

from .setup import default_template, d2_path, custom_template


def test_config():
    path = default_template(d2_path(gettempdir()))
    cfg = dk.load_config(os.path.join(path, 'config.py'))
    assert (cfg is not None)


def test_drive():
    path = default_template(d2_path(gettempdir()))
    myconfig = open(os.path.join(path, 'myconfig.py'), "wt")
    myconfig.write("CAMERA_TYPE = 'MOCK'\n")
    myconfig.write("USE_SSD1306_128_32 = False \n")
    myconfig.write("DRIVE_TRAIN_TYPE = 'None'")
    myconfig.close()
    cfg = dk.load_config(os.path.join(path, 'config.py'))
    cfg.MAX_LOOPS = 10
    complete.drive(cfg=cfg)


def test_custom_templates():
    template_names = ["complete", "basic", "square"]
    for template in template_names:
        path = custom_template(d2_path(gettempdir()), template=template)
        cfg = dk.load_config(os.path.join(path, 'config.py'))
        assert (cfg is not None)
        mcfg = dk.load_config(os.path.join(path, 'myconfig.py'))
        assert (mcfg is not None)


# --- DonkeyDrifter template import checks ---

_MAIN_VEHICLE_TEMPLATES = [
    "arduino_drive.py",
    "basic.py",
    "complete.py",
    "cv_control.py",
    "just_drive.py",
    "path_follow.py",
    "simulator.py",
    "square.py",
    "train.py",
]

_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "donkeycar" / "templates"


def test_main_vehicle_templates_use_donkeydrifter_top_level_import():
    for template_name in _MAIN_VEHICLE_TEMPLATES:
        source = (_TEMPLATES_DIR / template_name).read_text(encoding="utf-8")
        assert "import donkeydrifter as dk" in source, (
            f"{template_name} should use 'import donkeydrifter as dk'"
        )
        assert "import donkeycar as dk" not in source, (
            f"{template_name} should not use 'import donkeycar as dk' at top level"
        )


def test_main_vehicle_templates_use_donkeydrifter_submodule_imports():
    for template_name in _MAIN_VEHICLE_TEMPLATES:
        source = (_TEMPLATES_DIR / template_name).read_text(encoding="utf-8")
        assert "from donkeycar.parts" not in source, (
            f"{template_name} should use 'from donkeydrifter.parts' instead of 'from donkeycar.parts'"
        )
        assert "from donkeycar.pipeline" not in source, (
            f"{template_name} should use 'from donkeydrifter.pipeline' instead of 'from donkeycar.pipeline'"
        )
        assert "from donkeycar.templates" not in source, (
            f"{template_name} should use 'from donkeydrifter.templates' instead of 'from donkeycar.templates'"
        )
