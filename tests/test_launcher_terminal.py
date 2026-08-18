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


def test_terminal_page_auto_reconnects_and_preserves_session():
    """链路断开后自动退避重连接回原会话，而非只提示"会话已丢失"（issue #173）。"""
    source = _source()

    # onclose 先清连接超时定时器，再走 scheduleReconnect 自动退避重连
    assert "ws.onclose=function(){\n    clearTimeout(connectTimer);\n    if(exited)return;\n    scheduleReconnect();" \
        in source
    # 服务端 session 帧记录 sid，重连时带上 ?session=<sid> 接回原 PTY
    assert "lastSid=j.id;" in source
    assert "if(lastSid)url+='?session='+encodeURIComponent(lastSid);" in source
    # 重连失败接回（会话已过期被销毁）时清屏，避免新旧 shell 输出混在一起
    assert "if(lastSid!==null&&!j.reattached){term.reset();}" in source
    # 会话保持文案（中英双语）：不再使用旧的 lost 文案
    assert "closed:'连接已断开'" in source
    assert "reconnecting:'正在重新连接会话…'" in source
    assert "closed:'Disconnected'" in source
    assert "reconnecting:'Reconnecting session…'" in source


def test_terminal_page_has_connect_timeout():
    """WS 连接 10s 未完成必须超时报错，不得无限期停在「正在连接」（issue #101）。"""
    source = _source()

    # connect() 内建连接超时定时器（10s），超时时仍在 CONNECTING 则主动关闭；
    # 关闭后走 onclose → scheduleReconnect 统一退避重连（不再单独弹失败文案）
    assert "var connectTimer=setTimeout(function(){" in source
    assert "},10000);" in source
    assert "ws.readyState===WebSocket.CONNECTING" in source
    assert "try{ws.close();}catch(e){}" in source
    # onopen 落定后清掉超时定时器，正常连接不受影响
    assert "ws.onopen=function(){\n    clearTimeout(connectTimer);" in source
