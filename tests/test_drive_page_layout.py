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
# issue #003：选模型 = 车端带模型重启 + 重启后恢复全自动/半自动模式
# ===========================================================================
DRIVE_PAGE = REPO_ROOT / "web_ui" / "frontend" / "src" / "pages" / "DrivePage.tsx"


def test_drive_page_model_change_triggers_restart_state_machine():
    source = DRIVE_PAGE.read_text(encoding="utf-8")

    # 模式恢复状态机：后端确认重启后 begin，车端再上线时补发当前模式
    assert "useModelRestart" in source
    assert "beginModelRestart()" in source
    assert "res?.restarting" in source


def test_drive_page_suppresses_mode_sync_and_disables_selectors_during_restart():
    source = DRIVE_PAGE.read_text(encoding="utf-8")

    # 重启窗口内不跟随车端回报的默认 user 模式（否则全自动选择被冲掉）
    assert "if (!modelRestarting)" in source
    # 重启完成前禁用模式/模型切换
    assert "disabled={!carState.online || modelRestarting}" in source
    assert "disabled={!carState.online || modelsLoading || modelRestarting}" in source
    # 重启中与失败/需手动重启的可见提示
    assert "drive.modelRestarting" in source
    assert "modelNotice" in source
