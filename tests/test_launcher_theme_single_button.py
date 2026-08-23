from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_PY = REPO_ROOT / "donkeycar" / "launcher" / "server.py"


def _launcher_source() -> str:
    return LAUNCHER_PY.read_text(encoding="utf-8")


def test_launcher_menu_theme_is_mute_style_single_button():
    """菜单页主题切换：静音式单图标按钮（.langBtn 圆形 32×32），
    单击在 浅色/深色 两态间互切，图标按 html[data-theme]（生效主题）显隐。"""
    source = _launcher_source()

    # 单按钮入口存在，三态分段控件（#themeTabs）已移除
    assert 'id="themeBtn"' in source
    assert "#themeTabs" not in source
    assert "renderThemeTabs" not in source

    # 图标显隐由生效主题驱动：浅色显太阳，深色显月亮；无"跟随系统"显示器图标
    assert "#themeBtn .icon-sun{display:none}" in source
    assert "icon-monitor" not in source
    assert 'html[data-theme="light"] #themeBtn .icon-sun{display:block}' in source
    assert 'html[data-theme="light"] #themeBtn .icon-moon{display:none}' in source

    # 不再写 html[data-mode]，主题图标仅由生效主题 html[data-theme] 驱动
    assert "document.documentElement.dataset.mode" not in source

    # 皮肤与 DD ThemeSwitcher 渲染值逐值一致（langBtn 基类为原始 zinc 值，
    # #themeBtn 用 ID 覆盖为 DD theme-mus4/theme-light 重映射值）
    assert "#themeBtn{margin-left:auto;background:#111820;border-color:#344154;box-shadow:inset 0 0 0 1px #2b3441;color:#b9c5d3}" in source
    assert "#themeBtn:hover{color:#e8edf2}" in source
    assert '#themeBtn svg{width:16px;height:16px}' in source
    assert 'html[data-theme="light"] #themeBtn{background:#f4f6f9;border-color:#ccd5df;box-shadow:inset 0 0 0 1px #d5dce4;color:#3f4f63}' in source
    assert 'html[data-theme="light"] #themeBtn:hover{color:#1a2330}' in source


def test_launcher_theme_toggles_between_light_and_dark():
    """单击切换：toggleTheme 按生效主题在 浅色 ↔ 深色 间互切，
    setTheme 仅更新内存态，不写 localStorage（每次进入/刷新重新跟随系统）。"""
    source = _launcher_source()

    body = source.split("function toggleTheme()", 1)[1].split("function initTheme()", 1)[0]
    assert "var effective = document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';" in body
    assert "setTheme(effective === 'light' ? 'dark' : 'light');" in body

    toggle_binding = source.split("// 控件事件绑定", 1)[1]
    assert "document.getElementById('themeBtn')" in toggle_binding
    assert ".addEventListener('click', toggleTheme);" in toggle_binding


def test_launcher_theme_follows_browser_until_manual_click():
    """默认跟随浏览器：'system' 态经 matchMedia 实时解析并监听 prefers-color-scheme
    变化实时跟随；每次进入/刷新都重新跟随系统，手动单击仅当前视图内切换（不持久化）。"""
    source = _launcher_source()

    body = source.split("function initTheme()", 1)[1].split("// ── DC FAB", 1)[0]
    assert "applyTheme('system');" in body
    assert "matchMedia('(prefers-color-scheme: light)')" in body
    assert "if (uiTheme === 'system') applyTheme('system');" in body

    # 首屏防闪烁脚本：不读任何存储，直接按系统深浅色解析并写到 html[data-theme]，
    # 因此每次进入/刷新都会重新跟随系统
    assert "(function(){try{var r=(window.matchMedia&&window.matchMedia('(prefers-color-scheme: light)').matches)?'light':'dark';document.documentElement.dataset.theme=r}catch(e){}})();" in source
    assert "localStorage.getItem('donkeydrifter.ui.theme')" not in source
    assert "localStorage.setItem('donkeydrifter.ui.theme')" not in source
    assert "donkeydrifter.ui.theme.v3" not in source

    # 两态按钮不再提供"跟随系统"入口（无 followSystem/toggleSystem 文案）
    assert "'theme.followSystem'" not in source
    assert "'theme.toggleSystem'" not in source

    # 旧的三态分段控件文案（theme.auto）已清理
    assert "'theme.auto'" not in source
