import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = PROJECT_ROOT / "web_ui" / "frontend"


def read_text(path):
    return path.read_text(encoding="utf-8")


def test_frontend_package_uses_donkeydrifter_name():
    package_json = json.loads(read_text(FRONTEND_DIR / "package.json"))

    # npm 包名 donkeydrifter-web-ui 保留不动（避免破坏 lockfile / 已有引用）。
    assert package_json["name"] == "donkeydrifter-web-ui"


def test_frontend_html_title_uses_donkeydrifter_brand():
    html = read_text(FRONTEND_DIR / "index.html")

    assert "<title>DonkeyDrift Web UI</title>" in html


def test_layout_visible_brand_uses_donkeydrifter():
    layout = read_text(FRONTEND_DIR / "src" / "components" / "Layout.tsx")

    assert "DonkeyDrift" in layout
    assert "Donkey Car" not in layout
