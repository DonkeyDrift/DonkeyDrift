from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_PY = REPO_ROOT / "donkeycar" / "launcher" / "server.py"


def _launcher_source() -> str:
    return LAUNCHER_PY.read_text(encoding="utf-8")


def test_launcher_menu_theme_is_mute_style_single_button():
    """菜单页主题切换：静音式单图标按钮（.langBtn 圆形 32×32），
    单击在深/浅之间互切，太阳/月亮图标按 html[data-theme] 显隐。"""
    source = _launcher_source()

    # 单按钮入口存在，三态分段控件（#themeTabs）已移除
    assert 'id="themeBtn"' in source
    assert "#themeTabs" not in source
    assert "renderThemeTabs" not in source

    # 图标显隐由生效主题驱动：深色显月亮，浅色显太阳
    assert "#themeBtn .icon-sun{display:none}" in source
    assert 'html[data-theme="light"] #themeBtn .icon-sun{display:block}' in source
    assert 'html[data-theme="light"] #themeBtn .icon-moon{display:none}' in source

    # 皮肤与 DD ThemeSwitcher 渲染值逐值一致（langBtn 基类为原始 zinc 值，
    # #themeBtn 用 ID 覆盖为 DD theme-mus4/theme-light 重映射值）
    assert "#themeBtn{margin-left:auto;background:#111820;border-color:#344154;box-shadow:inset 0 0 0 1px #2b3441;color:#b9c5d3}" in source
    assert "#themeBtn:hover{color:#e8edf2}" in source
    assert '#themeBtn svg{width:16px;height:16px}' in source
    assert 'html[data-theme="light"] #themeBtn{background:#f4f6f9;border-color:#ccd5df;box-shadow:inset 0 0 0 1px #d5dce4;color:#3f4f63}' in source
    assert 'html[data-theme="light"] #themeBtn:hover{color:#1a2330}' in source


def test_launcher_theme_toggles_between_light_and_dark():
    """单击切换：toggleTheme 按当前生效主题取反（深↔浅），
    经 setTheme 持久化显式选择（沿用 donkeydrifter.ui.theme 键）。"""
    source = _launcher_source()

    body = source.split("function toggleTheme()", 1)[1].split("function initTheme()", 1)[0]
    assert "dataset.theme === 'light' ? 'light' : 'dark'" in body
    assert "setTheme(effective === 'light' ? 'dark' : 'light');" in body

    toggle_binding = source.split("// 控件事件绑定", 1)[1]
    assert "document.getElementById('themeBtn')" in toggle_binding
    assert ".addEventListener('click', toggleTheme);" in toggle_binding


def test_launcher_theme_follows_browser_until_manual_click():
    """默认跟随浏览器：无显式存储时 'system' 态经 matchMedia 实时解析，
    并监听 prefers-color-scheme 变化实时跟随；手动单击后写入显式选择不再跟随。"""
    source = _launcher_source()

    body = source.split("function initTheme()", 1)[1].split("// ── DC FAB", 1)[0]
    assert "if (s === 'light' || s === 'dark' || s === 'system') stored = s;" in body
    assert "matchMedia('(prefers-color-scheme: light)')" in body
    assert "if (uiTheme === 'system') applyTheme('system');" in body

    # 首屏防闪烁脚本：显式 light/dark 优先，否则跟随浏览器（浅色判定）
    assert "var t=localStorage.getItem('donkeydrifter.ui.theme');if(t!=='light'&&t!=='dark'){" in source
    assert "matchMedia('(prefers-color-scheme: light)').matches)?'light':'dark'" in source

    # 三态文案（theme.light/auto/dark）已随三态控件一并清理
    assert "'theme.auto'" not in source
