from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_PY = REPO_ROOT / "donkeycar" / "launcher" / "server.py"


def _launcher_source() -> str:
    return LAUNCHER_PY.read_text(encoding="utf-8")


def _launch_drive_page(source: str) -> str:
    start = source.index('LAUNCH_DRIVE_HTML = r"""')
    return source[start:source.index('"""', start + 25)]


def test_launcher_menu_initial_language_follows_browser():
    """菜单页初始语言：无显式存储选择时跟随浏览器语言（zh* → 中文，其余 → 英文）；
    用户手动切换后 localStorage 显式选择优先并跨重启保持（与 DD web_ui 同语义）。"""
    source = _launcher_source()

    assert "function detectBrowserLanguage()" in source
    assert "navigator.language" in source
    assert ".indexOf('zh') === 0 ? 'zh' : 'en'" in source

    # readStoredLanguage：存储的显式 zh/en 优先，否则回退浏览器检测（不再硬编码 'zh'）
    body = source.split("function readStoredLanguage()", 1)[1].split("function t(key)", 1)[0]
    assert "if (v === 'zh' || v === 'en') return v;" in body
    assert "return detectBrowserLanguage();" in body
    assert "catch (e) { return 'zh'; }" not in body

    # 初始渲染仍走 readStoredLanguage（自动检测入口）
    assert "applyLanguage(readStoredLanguage());" in source


def test_launcher_launch_drive_page_is_bilingual_and_follows_browser():
    """启动中转页 LAUNCH_DRIVE_HTML：中英双语字典 + 同一 localStorage 键
    （donkeydrifter.ui.lang，跟随菜单页显式选择）+ 无存储时跟随浏览器语言。"""
    page = _launch_drive_page(_launcher_source())

    # 语言解析：显式存储选择优先，否则 navigator.language（zh* → zh，其余 → en）
    assert "localStorage.getItem('donkeydrifter.ui.lang')" in page
    assert "if(v==='zh'||v==='en')return v;" in page
    assert "navigator.language" in page
    assert "indexOf('zh')===0?'zh':'en'" in page

    # 双语字典键对齐
    for key in ("starting", "failed", "unknown", "network"):
        assert f"{key}:" in page
    assert "starting:'正在启动 DonkeyDrifter...'" in page
    assert "starting:'Starting DonkeyDrifter...'" in page
    assert "failed:'启动失败'" in page
    assert "failed:'Launch failed'" in page
    assert "unknown:'未知错误'" in page
    assert "unknown:'Unknown error'" in page
    assert "network:'网络错误: '" in page
    assert "network:'Network error: '" in page

    # 所有用户可见文案经 t() 渲染，无残留硬编码中文
    assert "document.getElementById('text').textContent=t('starting');" in page
    assert page.count("document.getElementById('text').textContent=t('failed');") == 2
    assert "d.error||t('unknown')" in page
    assert "t('network')+e.message" in page
