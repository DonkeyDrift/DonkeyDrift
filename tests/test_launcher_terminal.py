# -*- coding: utf-8 -*-
"""上位机终端页（terminal_static/terminal.html）标签页命名逻辑的静态断言。

Drifter Console（ESP32 Web Console）的 Serial 终端标签页名字跟随
终端内输入的命令：终端页跟踪当前输入行，回车时把第一个词
（空格前内容，≤16 字符）通过 postMessage 发给父页改名。
全屏 TUI（备用屏幕缓冲区 ESC[?1049h/l，如 kimi/claude/codex）内
的按键不计入，避免在 TUI 里输入时误改标签名。
"""

from pathlib import Path

TERMINAL_HTML = (
    Path(__file__).resolve().parent.parent
    / "donkeycar" / "launcher" / "terminal_static" / "terminal.html"
)


def _source() -> str:
    return TERMINAL_HTML.read_text(encoding="utf-8")


def test_terminal_page_reports_first_word_of_each_command_line():
    source = _source()

    # 行缓冲跟踪挂在 term.onData 上（按键先转发 WebSocket，再进 trackLine）
    assert "term.onData(function(d){" in source
    assert "trackLine(d);" in source
    # 回车提交：取第一个空格前的词，空行不上报，名字截断到 16 字符
    assert "function commitLine()" in source
    assert "split(/\\s+/)[0]" in source
    assert "name.slice(0,16)" in source
    assert "window.parent.postMessage({type:'donkeydrifter.term.name',name:name},'*')" in source
    # 退格删除、Ctrl+C/ESC 清空缓冲（方向键等转义序列不会拼出假名字）
    assert "lineBuf=lineBuf.slice(0,-1);" in source
    assert "ch==='\\x03'||ch==='\\x1b'" in source


def test_terminal_page_suspends_tracking_in_alternate_screen():
    source = _source()

    # 从 PTY 输出流里扫描 ESC[?1049h/l 进入/退出备用屏幕缓冲区
    assert "function scanAltScreen(buf)" in source
    assert "scanAltScreen(bytes);" in source
    assert "inAlt=true" in source
    assert "inAlt=false" in source
    # 备用屏幕期间清空并暂停行缓冲
    assert "if(inAlt){lineBuf='';return;}" in source


def test_terminal_page_disconnect_overlay_warns_session_lost():
    """链路断开的 overlay 必须明确提示会话已丢失（issue #151）。"""
    source = _source()

    # onclose 提示「会话已丢失 · 点击重连（将开启新会话）」，中英双语
    assert "ws.onclose=function(){showOverlay(t('lost')+' · '+t('newSession'));};" \
        in source
    assert "lost:'连接已断开 · 终端会话已丢失'" in source
    assert "newSession:'点击重连（将开启新会话）'" in source
    assert "lost:'Disconnected · terminal session lost'" in source
