from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_TSX = REPO_ROOT / "web_ui" / "frontend" / "src" / "App.tsx"


def test_tub_manager_refreshes_only_when_tub_changes_or_manual_refresh():
    app_source = APP_TSX.read_text(encoding="utf-8")

    assert "loadTub" in app_source
    assert "getApiErrorMessage" in app_source
    # #135：不再按路由切换全量重拉，仅在 tub 变更或手动刷新（令牌递增）时拉取
    assert "loadedTubPath" in app_source
    assert "tubRefreshToken" in app_source
    assert "tubPath === loadedTubPath" in app_source
    assert "loadTub(tubPath)" in app_source
    assert "setTub(" in app_source
    assert "location.pathname === '/'" not in app_source
    assert "prevLocationRef" not in app_source
