from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TUB_MANAGER_PAGE = REPO_ROOT / "web_ui" / "frontend" / "src" / "pages" / "TubManagerPage.tsx"


def test_tub_manager_refreshes_only_when_tub_changes_or_manual_refresh():
    # #178：tub 自动刷新逻辑已从 App.tsx 迁到 TubManagerPage.tsx
    page_source = TUB_MANAGER_PAGE.read_text(encoding="utf-8")

    assert "loadTub" in page_source
    assert "getApiErrorMessage" in page_source
    # #135：不再按路由切换全量重拉，仅在 tub 变更或手动刷新（令牌递增）时拉取
    assert "loadedTubPath" in page_source
    assert "tubRefreshToken" in page_source
    assert "tubPath === loadedTubPath" in page_source
    assert "loadTub(tubPath)" in page_source
    assert "setTub(" in page_source
    assert "location.pathname === '/'" not in page_source
    assert "prevLocationRef" not in page_source
