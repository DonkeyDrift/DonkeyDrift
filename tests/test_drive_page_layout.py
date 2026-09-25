from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_TSX = REPO_ROOT / "web_ui" / "frontend" / "src" / "App.tsx"


def test_drive_page_does_not_mount_config_loaders():
    app_source = APP_TSX.read_text(encoding="utf-8")
    sidepanel_source = (APP_TSX.parent / "components" / "SidePanel.tsx").read_text(encoding="utf-8")

    # App.tsx mounts SidePanel unconditionally; visibility is managed internally
    assert "<SidePanel />" in app_source
    assert "shouldShowLoaders" not in app_source
    assert "pathname !== '/drive'" not in app_source

    # SidePanel uses activeDrawer state to control loader visibility
    assert "activeDrawer" in sidepanel_source
    assert "setActiveDrawer" in sidepanel_source


# ===========================================================================
# issue #003（热加载）：选模型 = 车端运行期热加载，无需重启车端进程
# ===========================================================================
DRIVE_PAGE = REPO_ROOT / "web_ui" / "frontend" / "src" / "pages" / "DrivePage.tsx"


def test_drive_page_model_change_requests_hot_load_without_restart():
    source = DRIVE_PAGE.read_text(encoding="utf-8")

    # 选模型经后端下发车端热加载；只有车端离线/旧版才回退提示重启
    assert "loadModelToCar" in source
    assert "res?.restart_required" in source
    assert "drive.modelLoaded" in source
    assert "drive.modelLoading" in source


def test_drive_page_hot_load_shows_loading_and_disables_model_selector():
    source = DRIVE_PAGE.read_text(encoding="utf-8")

    # 加载期间禁用模型选择并显示加载态；结果用 modelNotice 展示
    assert "disabled={!carState.online || modelsLoading || modelLoading}" in source
    assert "data-model-loading" in source
    assert "modelNotice" in source
