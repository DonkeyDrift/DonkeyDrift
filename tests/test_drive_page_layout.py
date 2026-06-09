from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_TSX = REPO_ROOT / "web_ui" / "frontend" / "src" / "App.tsx"


def test_drive_page_does_not_mount_config_loaders():
    app_source = APP_TSX.read_text(encoding="utf-8")

    assert "shouldShowLoaders" in app_source
    assert "pathname !== '/drive'" in app_source
    assert "{shouldShowLoaders && <SidePanel />" in app_source
