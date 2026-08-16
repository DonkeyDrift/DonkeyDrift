"""DonkeyDrifter Web Launcher 服务端模块。

基于 Python 标准库 http.server 实现，提供浏览器端的 TUI 菜单复刻和
一键启动 donkey web + manage.py drive 的能力。
仅依赖标准库，无需 Flask/FastAPI 等第三方框架。
"""

import http.server
import json
import os
import signal
import socket
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import urlparse

from donkeycar._version import __version__
from donkeycar.launcher.dc_discovery import find_drifter_console
from donkeycar.launcher.kimi_web import launch_kimi_code_web
from donkeycar.launcher.terminal import handle_terminal_ws
from donkeycar.webui_instance import (
    find_live_instance,
    write_drive_pids,
    remove_drive_pid_file,
    kill_previous_car_processes,
)


# ── 图标静态文件 ────────────────────────────────────────────────────

# URL 路径 → (文件名, Content-Type)，文件位于本模块同目录。
# favicon.svg 是 Safari 固定标签页的 mask-icon（单色头盔描摹自 logo.png），
# apple-touch-icon 用于 Safari 收藏/书签，favicon.ico 兼容旧路径请求。
_ICON_FILES = {
    "/favicon.png": ("donkey_favicon.png", "image/png"),
    "/favicon.ico": ("donkey_favicon.ico", "image/x-icon"),
    "/favicon.svg": ("donkey_favicon.svg", "image/svg+xml"),
    "/apple-touch-icon.png": ("donkey_touch_icon.png", "image/png"),
}

# 上位机终端（/terminal）静态资源目录与白名单：URL 路径段 → (文件名, Content-Type)。
# xterm.js / addon-fit.js 为 MIT 许可的 vendored 依赖（LICENSE-xterm.txt）。
_TERMINAL_STATIC_DIR = Path(__file__).parent / "terminal_static"
_TERMINAL_STATIC_FILES = {
    "xterm.js": ("xterm.js", "text/javascript; charset=utf-8"),
    "xterm.css": ("xterm.css", "text/css; charset=utf-8"),
    "addon-fit.js": ("addon-fit.js", "text/javascript; charset=utf-8"),
    "LICENSE-xterm.txt": ("LICENSE-xterm.txt", "text/plain; charset=utf-8"),
}


# ── 项目查找与端口选择 ──────────────────────────────────────────────

def _is_valid_project_dir(project_path):
    """检查目录是否为有效的 mycar 项目。"""
    project_path = Path(project_path)
    return (project_path / "manage.py").exists() and \
           (project_path / "myconfig.py").exists()


def _find_mycar_project():
    """查找 mycar 项目路径：先检查 CWD，再搜索已知路径。"""
    # 检查当前工作目录
    cwd = Path.cwd()
    if _is_valid_project_dir(cwd):
        return cwd
    # 搜索 /home/dkc/projects/mycar
    known_path = Path("/home/dkc/projects/mycar")
    if _is_valid_project_dir(known_path):
        return known_path
    return None


def _get_bundled_web_ui_path():
    """获取随源码仓库提供的 Web UI 目录。

    server.py 位于 donkeycar/launcher/server.py，
    parents[2] 即仓库根目录。
    """
    web_ui_path = Path(__file__).resolve().parents[2] / "web_ui"
    if (web_ui_path / "frontend").is_dir() and \
       (web_ui_path / "backend").is_dir():
        return web_ui_path
    return None


def _choose_available_backend_port(preferred_port=8100):
    """从 preferred_port 开始寻找可用端口，最多尝试 100 个。"""
    port = preferred_port
    while port < preferred_port + 100:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("0.0.0.0", port))
                return port
            except OSError:
                port += 1
    return preferred_port


# ── 进程跟踪 ──────────────────────────────────────────────────────

_proc_lock = threading.Lock()
_processes = {
    "web": None,
    "car": None,
    "backend_port": None,
    "frontend_port": None,
    "project": None,
}


def _launch_drive():
    """启动 donkey web + manage.py drive，返回结果字典。

    issue #127：先只杀上一次的车进程（manage.py drive，释放摄像头等
    硬件），再探测存活的 Web UI 实例（~/.donkeycar/webui.json）——
    存活则复用、只起新车进程；没有才用默认端口（8000/5188）新起
    `donkey web`（由其自行登记实例）。不再 pkill 互杀、不再端口漂移。
    """
    with _proc_lock:
        # 只杀上一次的车进程；web 前后端进程保留复用
        kill_previous_car_processes()

        # 查找 mycar 项目
        project_path = _find_mycar_project()
        if project_path is None:
            return {
                "status": "error",
                "error": "未找到有效的 mycar 项目"
                         "（需包含 manage.py 和 myconfig.py）",
            }

        # 探测存活的 Web UI 实例（donkey web / donkey drive 启动时登记）
        inst = find_live_instance()

        creationflags = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            if sys.platform == "win32" else 0
        )

        if inst:
            # 复用已有实例：只启动车进程，连回已有后端
            backend_port = inst["backend_port"]
            frontend_port = inst["frontend_port"]
            web_proc = None
            print(f"[launcher] 复用运行中的 Web UI 实例 "
                  f"(backend=:{backend_port} frontend=:{frontend_port})")
        else:
            # 无实例：用默认端口新起 donkey web（不再从 8100 漂移），
            # web 进程启动成功后自行登记实例
            backend_port = _choose_available_backend_port(8000)
            frontend_port = _choose_available_backend_port(5188)
            web_ui_path = _get_bundled_web_ui_path()
            web_cmd = ["donkey", "web"]
            if web_ui_path is not None:
                web_cmd.extend(["--path", str(web_ui_path)])
            web_cmd.extend(["--backend-port", str(backend_port)])
            web_cmd.extend(["--frontend-port", str(frontend_port)])

        # 构建 car 命令
        car_cmd = [sys.executable, "manage.py", "drive"]

        # 设置环境变量
        car_env = os.environ.copy()
        car_env["DRIVE_API_SERVER_URL"] = \
            f"ws://localhost:{backend_port}/api/drive/ws"

        # 启动进程
        try:
            if inst is None:
                web_proc = subprocess.Popen(
                    web_cmd,
                    stdin=subprocess.DEVNULL,
                    creationflags=creationflags,
                )
            car_proc = subprocess.Popen(
                car_cmd,
                cwd=str(project_path),
                env=car_env,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        except FileNotFoundError:
            return {
                "status": "error",
                "error": "未找到 donkey 命令，请确认 donkeycar 已正确安装",
            }
        except Exception as e:
            return {
                "status": "error",
                "error": f"启动进程失败: {e}",
            }

        # 写入 PID 文件（复用实例时 web 进程不归本链路管，只记车进程）
        if web_proc is not None:
            write_drive_pids([web_proc.pid, car_proc.pid])
        else:
            write_drive_pids([car_proc.pid])

        # 记录进程信息
        _processes["web"] = web_proc
        _processes["car"] = car_proc
        _processes["backend_port"] = backend_port
        _processes["frontend_port"] = frontend_port
        _processes["project"] = str(project_path)

        return {
            "status": "launched",
            "url": f"http://localhost:{frontend_port}/#/drive",
            "backend_port": backend_port,
            "frontend_port": frontend_port,
            "project": str(project_path),
            "warning": None,
        }


def _get_status():
    """获取当前进程状态。

    issue #127：launcher 本次会话未跟踪进程时，优先读实例登记
    （~/.donkeycar/webui.json）——其它链路（donkey web/drive、TUI）启动
    的 Web UI 也算 running，避免状态显示"未运行"导致重复拉起。
    """
    with _proc_lock:
        web_proc = _processes["web"]
        car_proc = _processes["car"]
        backend_port = _processes["backend_port"]
        frontend_port = _processes["frontend_port"]
        running = web_proc is not None and web_proc.poll() is None

        if not running:
            inst = find_live_instance()
            if inst:
                running = True
                backend_port = inst["backend_port"]
                frontend_port = inst["frontend_port"]
                web_proc = None

        project = _processes["project"]
        return {
            "running": running,
            "project": project or str(
                _find_mycar_project() or Path.cwd()
            ),
            "backend_port": backend_port,
            "frontend_port": frontend_port,
            "url": f"http://localhost:{frontend_port}/#/drive" if frontend_port else None,
            "web_pid": web_proc.pid if web_proc else None,
            "car_pid": car_proc.pid if car_proc else None,
            "car_running": (
                car_proc is not None and car_proc.poll() is None
            ),
        }


# ── HOSTIP 串口报告（让 ESP32 /api/status 输出 host_ip） ──────────────

# ESP32 配网串口（Serial2）候选设备：车上上位机经 UART 直连为 /dev/ttyS6，
# 其余为 USB 线直连 ESP32 时的常见设备名
_HOSTIP_SERIAL_PORTS = ("/dev/ttyS6", "/dev/ttyACM0", "/dev/ttyACM1",
                        "/dev/ttyUSB0")
# 与固件 Serial2 波特率（BAUD_RATE_1）一致
_HOSTIP_SERIAL_BAUD = 115200

try:
    import termios
except ImportError:  # 非 POSIX 平台无串口上报
    termios = None  # type: ignore[assignment]


def _get_local_ip():
    """获取本机局域网 IP（复用配网模块的 VPN/TUN 感知探测）。"""
    try:
        from donkeycar.parts.provisioning import detect_lan_ip
        return detect_lan_ip()
    except Exception:
        return None


def _report_hostip_to_esp32():
    """通过串口向 ESP32 报告本机 IP（HOSTIP|<ipv4> 帧）。

    每次发送都重新打开端口并显式 tcsetattr 波特率：ModemManager 等外部
    进程探测串口会把 termios 改掉（实测车上 ttyS6 被改成 9600），若在
    进程启动时只配置一次，被篡改后发出的帧对固件而言全是乱码；每次发送
    前重设可在下一个周期自愈。
    """
    local_ip = _get_local_ip()
    if not local_ip:
        return
    frame = f"HOSTIP|{local_ip}\n".encode("ascii")
    for port in _HOSTIP_SERIAL_PORTS:
        try:
            fd = os.open(port, os.O_WRONLY | os.O_NOCTTY | os.O_NONBLOCK)
        except OSError:
            continue
        try:
            if termios is not None:
                attrs = termios.tcgetattr(fd)
                attrs[4] = attrs[5] = termios.B115200  # ispeed/ospeed
                # 8N1、无校验，使能接收与本地连接（无视载波）
                attrs[2] &= ~(termios.CSIZE | termios.PARENB
                              | termios.CSTOPB)
                attrs[2] |= termios.CS8 | termios.CLOCAL | termios.CREAD
                attrs[1] &= ~termios.ONLCR  # 关闭输出换行翻译
                termios.tcsetattr(fd, termios.TCSANOW, attrs)
            os.write(fd, frame)
            if termios is not None:
                termios.tcdrain(fd)  # 等字节真正移位发出再关闭
            break  # 成功写入一个即可
        except OSError:
            pass
        finally:
            try:
                os.close(fd)
            except OSError:
                pass


def _hostip_reporter_loop():
    """后台线程：定期向 ESP32 报告本机 IP。"""
    while True:
        try:
            _report_hostip_to_esp32()
        except Exception:
            pass
        threading.Event().wait(30)


def _start_hostip_reporter():
    """启动 HOSTIP 报告后台线程（daemon）。"""
    t = threading.Thread(target=_hostip_reporter_loop, daemon=True)
    t.start()


# ── HTTP 请求处理 ──────────────────────────────────────────────────

# /api/launch/kimi-code-web 的 CORS 响应头：DC 页面由 ESP32 提供服务，浏览器
# 从 ESP32 的 origin 跨域 fetch 上位机 :8090（空体 POST，simple request，
# 无预检）；没有 Access-Control-Allow-Origin 浏览器会拦截响应，DC 按钮永远
# 失败。仅该端点放行，不扩散到其它端点。
_KIMI_WEB_CORS_HEADERS = (("Access-Control-Allow-Origin", "*"),)


class LauncherHandler(http.server.BaseHTTPRequestHandler):
    """Launcher HTTP 请求处理器。"""

    def do_GET(self):
        """处理 GET 请求。"""
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            self._serve_html()
        elif path in _ICON_FILES:
            self._serve_icon(path)
        elif path == "/launch/drive":
            self._serve_launch_drive_page()
        elif path == "/terminal" or path == "/terminal/index.html":
            self._serve_terminal_page()
        elif path.startswith("/terminal/static/"):
            self._serve_terminal_static(path)
        elif path == "/terminal/ws":
            # WebSocket 升级：连接被终端桥接管，直到断开后才返回
            handle_terminal_ws(self)
        elif path == "/api/status":
            self._serve_json(_get_status())
        else:
            self._serve_json({"error": "not found"}, code=404)

    def do_POST(self):
        """处理 POST 请求。"""
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/launch/drive":
            # 读取并丢弃请求体（如有）
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 0:
                self.rfile.read(content_length)
            result = _launch_drive()
            code = 200 if result.get("status") != "error" else 500
            self._serve_json(result, code=code)
        elif path == "/api/launch/dc":
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 0:
                self.rfile.read(content_length)
            url = find_drifter_console()
            if url:
                self._serve_json({"status": "ok", "url": url})
            else:
                self._serve_json({"status": "not_found"})
        elif path == "/api/launch/kimi-code-web":
            self._handle_launch_kimi_code_web()
        else:
            self._serve_json({"error": "not found"}, code=404)

    def _handle_launch_kimi_code_web(self):
        """POST /api/launch/kimi-code-web：启动 kimi 并注入 /web，回 URL。

        请求体可选 JSON {"cwd": "/abs/path"} 指定 kimi 运行目录，缺省为
        上位机用户主目录；cwd 不存在直接报错，绝不回退到其它目录。
        长请求：kimi 冷启动可达数十秒，服务端整体超时 120s，
        客户端超时必须 ≥120s。所有响应带 CORS 头（DC 跨域调用，
        见 _KIMI_WEB_CORS_HEADERS）。
        """
        content_length = int(self.headers.get("Content-Length", 0))
        cwd = None
        if content_length > 0:
            raw = self.rfile.read(content_length)
            try:
                body = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._serve_json(
                    {"status": "error", "error": "请求体不是合法 JSON"},
                    code=400, extra_headers=_KIMI_WEB_CORS_HEADERS,
                )
                return
            if not isinstance(body, dict):
                self._serve_json(
                    {"status": "error", "error": "请求体必须是 JSON 对象"},
                    code=400, extra_headers=_KIMI_WEB_CORS_HEADERS,
                )
                return
            cwd = body.get("cwd")
            if cwd is not None and not isinstance(cwd, str):
                self._serve_json(
                    {"status": "error", "error": "cwd 必须是字符串"},
                    code=400, extra_headers=_KIMI_WEB_CORS_HEADERS,
                )
                return
        result = launch_kimi_code_web(cwd=cwd)
        code = 200 if result.get("status") == "ok" else 500
        self._serve_json(result, code=code,
                         extra_headers=_KIMI_WEB_CORS_HEADERS)

    def _serve_html(self):
        """提供菜单 HTML 页面。"""
        html = MENU_HTML.replace("{{CWD}}", str(Path.cwd()))
        html = html.replace("{{VERSION}}", __version__)
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_icon(self, path):
        """提供图标静态文件（favicon PNG/ICO/SVG、apple-touch-icon）。"""
        filename, content_type = _ICON_FILES[path]
        icon_path = Path(__file__).parent / filename
        if icon_path.exists():
            body = icon_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-cache")
            self.send_header(
                "Last-Modified",
                self.date_time_string(icon_path.stat().st_mtime)
            )
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def _serve_launch_drive_page(self):
        """提供启动 DonkeyDrifter 的跳转页面（GET /launch/drive）。

        返回一个极简 HTML 页面，页面加载后自动 POST /api/launch/drive
        （同源请求，无需 CORS），拿到 drive URL 后重定向当前标签页。
        """
        body = LAUNCH_DRIVE_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_terminal_page(self):
        """提供上位机终端页面（GET /terminal）。

        页面加载 /terminal/static/ 下的 xterm.js 并连接 /terminal/ws，
        内容由 Drifter Console 的 Serial 目标以 iframe 嵌入，也可直接
        在浏览器新标签页打开。每次实时读取文件，便于前端迭代免重启。
        """
        page = _TERMINAL_STATIC_DIR / "terminal.html"
        if not page.exists():
            self._serve_json({"error": "terminal not installed"}, code=404)
            return
        body = page.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_terminal_static(self, path):
        """提供终端页面依赖的静态资源（白名单，防路径穿越）。

        xterm.js 等库文件内容随版本固定，可长缓存。
        """
        name = path[len("/terminal/static/"):]
        filename, content_type = _TERMINAL_STATIC_FILES.get(
            name, (None, None))
        if filename is None:
            self._serve_json({"error": "not found"}, code=404)
            return
        asset = _TERMINAL_STATIC_DIR / filename
        if not asset.exists():
            self._serve_json({"error": "not found"}, code=404)
            return
        body = asset.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "max-age=86400")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_json(self, data, code=200, extra_headers=None):
        """提供 JSON 响应。extra_headers 为额外的响应头名值对序列（如
        _KIMI_WEB_CORS_HEADERS），仅需要跨域放行的端点使用。"""
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header(
            "Content-Type", "application/json; charset=utf-8"
        )
        for header_name, header_value in extra_headers or ():
            self.send_header(header_name, header_value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        """简化日志输出。"""
        sys.stderr.write(
            f"[launcher] {self.address_string()} - {format % args}\n"
        )


def run_server(host="0.0.0.0", port=8090):
    """启动 Launcher HTTP 服务器。"""
    # 启动 HOSTIP 报告后台线程
    _start_hostip_reporter()
    server = http.server.ThreadingHTTPServer(
        (host, port), LauncherHandler
    )
    print(f"DonkeyDrifter Launcher 服务已启动: http://{host}:{port}")
    print(f"当前工作目录: {Path.cwd()}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止服务...")
        server.shutdown()


# ── 菜单 HTML 页面（嵌入为字符串常量） ──────────────────────────────

LAUNCH_DRIVE_HTML = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" type="image/png" href="/favicon.png">
<link rel="mask-icon" href="/favicon.svg" color="#5cc8ff">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<title>Donkey</title>
<style>
body{font-family:system-ui,sans-serif;margin:0;background:#101318;color:#e8edf2;display:flex;justify-content:center;align-items:center;min-height:100vh}
.box{text-align:center}
.spinner{width:40px;height:40px;border:3px solid #2b3441;border-top-color:#5cc8ff;border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 16px}
@keyframes spin{to{transform:rotate(360deg)}}
.text{font-size:16px}
.error{color:#ff6b6b;margin-top:12px;font-size:14px}
</style>
</head>
<body>
<div class="box">
<div class="spinner" id="spinner"></div>
<div class="text" id="text">正在启动 DonkeyDrifter...</div>
<div class="error" id="error"></div>
</div>
<script>
// 语言：显式存储选择优先，否则跟随浏览器语言（zh* → 中文，其余 → 英文）
var uiLang=(function(){try{var v=localStorage.getItem('donkeydrifter.ui.lang');if(v==='zh'||v==='en')return v;}catch(e){}try{return String(navigator.language||'').toLowerCase().indexOf('zh')===0?'zh':'en';}catch(e){return 'zh';}})();
var T={
  zh:{starting:'正在启动 DonkeyDrifter...',failed:'启动失败',unknown:'未知错误',network:'网络错误: '},
  en:{starting:'Starting DonkeyDrifter...',failed:'Launch failed',unknown:'Unknown error',network:'Network error: '}
};
function t(k){return (T[uiLang]&&T[uiLang][k])||T.zh[k]||k;}
document.documentElement.lang=uiLang==='zh'?'zh-CN':'en';
document.getElementById('text').textContent=t('starting');
(async function(){
  try{
    var r=await fetch('/api/launch/drive',{method:'POST'});
    var d=await r.json();
    if(d.status==='launched'){
      var url=d.url.replace('localhost',window.location.hostname);
      window.location.href=url;
    }else{
      document.getElementById('spinner').style.display='none';
      document.getElementById('text').textContent=t('failed');
      document.getElementById('error').textContent=d.error||t('unknown');
    }
  }catch(e){
    document.getElementById('spinner').style.display='none';
    document.getElementById('text').textContent=t('failed');
    document.getElementById('error').textContent=t('network')+e.message;
  }
})();
</script>
</body>
</html>
"""

MENU_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script>
    // 首屏防闪烁：渲染前应用持久化主题（与 DD/DC 同一模式，默认跟随系统，经 matchMedia 实时解析）
    (function(){try{var t=localStorage.getItem('donkeydrifter.ui.theme');if(t!=='light'&&t!=='dark'){t=(window.matchMedia&&window.matchMedia('(prefers-color-scheme: light)').matches)?'light':'dark'}document.documentElement.dataset.theme=t}catch(e){}})();
    </script>
    <link rel="icon" type="image/png" href="/favicon.png">
    <link rel="mask-icon" href="/favicon.svg" color="#5cc8ff">
    <link rel="apple-touch-icon" href="/apple-touch-icon.png">
    <title>Donkey</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        html{color-scheme:dark}
        body{
            background:#101318;color:#e8edf2;
            font-family:system-ui,sans-serif;
            margin:12px;min-height:100vh;
        }
        .container{width:100%;margin:0}

        /* DC headerRow（整行垂直居中：logo/标题/GitHub/版本号/两个切换胶囊） */
        .headerRow{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:0 0 10px}
        .headerLogo{width:32px;height:32px;border-radius:8px;border:1px solid #2b3441}
        .logoLink{display:inline-flex}
        .headerRow h1{font-size:22px;margin:0}
        /* DD GitHubLink / VersionBadge */
        .ghLink{display:inline-flex;align-items:center;color:#8fa1b5}
        .ghLink:hover{color:#5cc8ff}
        .versionBadge{color:#6b7d90;font-size:12px;text-transform:uppercase;letter-spacing:.05em;display:inline-block}

        /* DD ThemeSwitcher / LanguageSwitcher（顶栏主题/语言分段控件，
           逐值复刻 DD 实际渲染值——Tailwind 类经 src/themes/theme-mus4.css
           重映射：容器 bg-zinc-800→#111820、border-zinc-700→#344154 外加
           1px #2b3441 内描边，p-1/gap-1；按钮 px-3 py-1 text-xs，未激活
           text-zinc-400→#8fa1b5、hover 仅文字变 #e8edf2，激活
           bg-cyan-600→#5cc8ff + 近黑 #061019 + 字重 800；
           浅色变体见下方 html[data-theme="light"] 段（theme-light.css 值）） */
        .langTabs{display:inline-flex;align-items:center;gap:4px;background:#111820;border:1px solid #344154;box-shadow:inset 0 0 0 1px #2b3441;border-radius:9999px;padding:4px;box-sizing:border-box}
        .langTabs button{padding:4px 12px;min-width:0;border:none;border-radius:9999px;background:transparent;color:#8fa1b5;font-size:12px;font-weight:400;line-height:16px;white-space:nowrap;cursor:pointer;transition:color .15s cubic-bezier(.4,0,.2,1),background-color .15s cubic-bezier(.4,0,.2,1)}
        .langTabs button:not(.active):hover{color:#e8edf2}
        .langTabs button.active{background:#5cc8ff;color:#061019;font-weight:800}
        #themeTabs{margin-left:auto}
        .headerBreak{display:none}

        /* 手机版顶栏两行：第一行 图标/标题/GitHub/版本号（与电脑版一致），
           第二行 主题切换(最左) + 中英文切换(最右) */
        @media (max-width:640px){
            .headerBreak{display:block;width:100%;height:0}
            #themeTabs{margin-left:0}
            #langTabs{margin-left:auto}
        }

        /* DC panel */
        .panel{background:#171c24;border:1px solid #2b3441;border-radius:8px;padding:10px}

        /* DC section title */
        .sectionTitle{font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:#d6deea;margin-bottom:8px}

        /* DC label */
        .label{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:#8fa1b5}

        /* CWD bar */
        .cwdBar{background:#111820;border:1px solid #2b3441;border-radius:10px;padding:10px 12px;margin-bottom:10px;display:flex;align-items:center;gap:8px}
        .cwdBar .path{font-family:Consolas,monospace;color:#5cc8ff;font-size:13px;word-break:break-all}

        /* Menu items as DC state cards */
        .menuGrid{display:grid;gap:8px}
        .menuItem{
            background:linear-gradient(135deg,#1c2430,#121821);
            border:1px solid #344154;border-radius:10px;padding:12px;
            cursor:pointer;transition:.25s;
            display:flex;align-items:center;gap:12px;
        }
        .menuItem:hover{border-color:#5cc8ff;background:linear-gradient(135deg,#1c2430,#151f2a)}
        .menuItem.selected{border-color:#5cc8ff;box-shadow:0 0 12px rgba(92,200,255,.2)}

        /* Number badge (monospace cyan) */
        .menuNo{flex:none;width:32px;height:32px;display:flex;align-items:center;justify-content:center;font:800 16px Consolas,monospace;color:#5cc8ff;background:#0d1219;border:1px solid #2b3441;border-radius:8px}

        /* Category pill (DC semantic colors) */
        .catPill{flex:none;display:inline-flex;align-items:center;padding:3px 10px;border-radius:999px;font-size:11px;font-weight:800;letter-spacing:.05em}
        .cat-manage{background:rgba(92,200,255,.12);color:#5cc8ff;border:1px solid rgba(92,200,255,.3)}
        .cat-data{background:rgba(57,217,138,.12);color:#39d98a;border:1px solid rgba(57,217,138,.3)}
        .cat-drive{background:rgba(255,204,102,.12);color:#ffcc66;border:1px solid rgba(255,204,102,.3)}
        .cat-filter{background:rgba(217,107,255,.12);color:#d96bff;border:1px solid rgba(217,107,255,.3)}
        .cat-train{background:rgba(255,107,107,.12);color:#ff6b6b;border:1px solid rgba(255,107,107,.3)}

        /* 英文版分类标签等宽：中文均为二字天然等宽，英文 Manage/Data/Drive/Filter/Train
           宽度不一导致各行标题错位，固定宽度后标题左对齐（电脑版与手机版同效） */
        html[lang="en"] .catPill{width:70px;justify-content:center}

        /* Menu item content */
        .menuContent{flex:1;min-width:0}
        .menuName{font-size:15px;font-weight:700;color:#e8edf2}
        .menuName .favorite{color:#d96bff;font-size:11px;margin-left:4px}
        .menuDesc{font-size:12px;color:#8fa1b5;margin-top:2px}

        /* DC reconnect overlay */
        .reconnectOverlay{position:fixed;inset:0;background:rgba(16,19,24,.88);display:none;align-items:center;justify-content:center;z-index:100}
        .reconnectOverlay.show{display:flex}
        .reconnectBox{text-align:center;color:#e8edf2}
        .reconnectSpinner{width:48px;height:48px;border:4px solid #2b3441;border-top-color:#5cc8ff;border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 16px}
        .reconnectText{font-size:16px;line-height:1.6}
        .reconnectError{color:#ff6b6b;margin-top:8px;font-size:14px}
        @keyframes spin{to{transform:rotate(360deg)}}

        /* DC FAB（右下角帮助小点，逐字对齐 WebConsoleAssets.h） */
        .fabToggle{position:fixed;right:24px;bottom:24px;width:18px;height:18px;min-width:0;padding:0;border-radius:50%;background:#8bdcff;border:1px solid #8bdcff;z-index:17;box-shadow:0 0 18px #5cc8ff,0 0 36px rgba(92,200,255,.55);cursor:pointer;transition:transform .18s}
        .fabToggle:hover,.fabToggle:focus-visible,.fabToggle:active{background:#8bdcff;border-color:#8bdcff;transform:scale(1.18);box-shadow:0 0 22px #8bdcff,0 0 44px rgba(92,200,255,.72)}
        .fabActions{position:fixed;right:18px;bottom:18px;z-index:17;pointer-events:none}
        .fabActions .langFab,.fabActions .helpFab{position:absolute;right:0;bottom:0;opacity:0;transform:scale(.55);pointer-events:none;transition:opacity .18s,transform .18s;display:flex;align-items:center;justify-content:center;cursor:pointer}
        .fabActions.show .langFab{opacity:1;transform:translateY(-56px) scale(1);pointer-events:auto}
        .fabActions.show .helpFab{opacity:1;transform:translateX(-56px) scale(1);pointer-events:auto}
        .fabActions .helpFab{width:46px;height:46px;min-width:0;padding:0;border-radius:50%;background:rgba(92,200,255,.62);color:#061019;border:1px solid rgba(92,200,255,.72);font-size:24px;font-weight:900;line-height:1;box-shadow:0 8px 22px rgba(0,0,0,.22);backdrop-filter:blur(4px)}
        .fabActions .helpFab:hover,.fabActions .helpFab:focus-visible{background:#8bdcff;border-color:#8bdcff;box-shadow:0 12px 32px rgba(0,0,0,.35)}
        .fabActions .langFab{width:46px;height:46px;min-width:0;padding:0;border-radius:50%;background:rgba(37,99,235,.58);color:#eef;border:1px solid rgba(92,200,255,.68);font-size:23px;font-weight:900;line-height:1;box-shadow:0 8px 22px rgba(0,0,0,.22);backdrop-filter:blur(4px)}
        .fabActions .langFab:hover,.fabActions .langFab:focus-visible{background:#3b82f6;border-color:#5cc8ff;box-shadow:0 12px 32px rgba(0,0,0,.35)}
        .langMenu{position:fixed;right:72px;bottom:74px;display:none;min-width:132px;background:#111820;border:1px solid #5cc8ff;border-radius:12px;padding:6px;z-index:17;box-shadow:0 12px 32px rgba(0,0,0,.35)}
        .langMenu.show{display:block}
        .langMenu button{display:block;width:100%;min-width:0;text-align:left;margin:2px 0;padding:7px 10px;background:transparent;border:none;border-radius:8px;color:#dbeafe;font-size:13px;cursor:pointer}
        .langMenu button:hover{background:#222b36}
        .langMenu button.active{background:#5cc8ff;color:#061019;font-weight:800}

        /* DC 帮助面板（锚定右下角 FAB 簇上方） */
        .helpOverlay{position:fixed;inset:0;display:none;background:rgba(5,7,10,.45);z-index:18}
        .helpOverlay.show{display:block}
        .helpModal{position:fixed;right:18px;bottom:74px;width:min(340px,calc(100vw - 36px));max-height:calc(100vh - 100px);overflow-y:auto;display:none;background:linear-gradient(135deg,#1c2430,#121821);border:1px solid #5cc8ff;border-radius:14px;padding:14px;box-shadow:0 18px 60px rgba(0,0,0,.45);color:#dbeafe;z-index:19}
        .helpModal.show{display:block}
        .helpHead{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:8px}
        .helpHead h2{margin:0;font-size:16px;font-weight:700;color:#e8edf2}
        .helpClose{min-width:0;width:28px;height:28px;padding:0;border:none;border-radius:50%;background:transparent;color:#a1a1aa;font-size:20px;line-height:1;cursor:pointer}
        .helpClose:hover{background:#27272a;color:#f4f4f5}
        .helpSection{margin-bottom:16px}
        .helpSection:last-child{margin-bottom:0}
        .helpSection h3{margin:0 0 8px;font-size:12px;font-weight:500;text-transform:uppercase;letter-spacing:.05em;color:#8fa1b5}
        .helpList{margin:0;padding-left:18px;color:#dbeafe;font-size:13px;line-height:1.55}
        .helpList li{margin:0 0 8px}

        /* ── 浅色主题（逐字对齐 DC WebConsoleAssets.h / DD theme-light.css 浅色版） ── */
        html[data-theme="light"]{color-scheme:light}
        html[data-theme="light"] body{background:#eef1f5;color:#1a2330}
        html[data-theme="light"] .headerLogo{border-color:#d5dce4}
        html[data-theme="light"] .ghLink{color:#5b6b7d}
        html[data-theme="light"] .ghLink:hover{color:#0c9bd6}
        html[data-theme="light"] .versionBadge{color:#7c8da0}
        html[data-theme="light"] .panel{background:#fff;border-color:#d5dce4}
        html[data-theme="light"] .sectionTitle{color:#3f4f63}
        html[data-theme="light"] .label{color:#5b6b7d}
        html[data-theme="light"] .cwdBar{background:#f4f6f9;border-color:#d5dce4}
        html[data-theme="light"] .cwdBar .path{color:#0c9bd6}
        html[data-theme="light"] .menuItem{background:linear-gradient(135deg,#fff,#edf1f6);border-color:#ccd5df;box-shadow:0 1px 3px rgba(15,23,42,.08)}
        html[data-theme="light"] .menuItem:hover{border-color:#0c9bd6;background:linear-gradient(135deg,#fff,#e8f4fb)}
        html[data-theme="light"] .menuItem.selected{border-color:#0c9bd6;box-shadow:0 0 12px rgba(12,155,214,.18)}
        html[data-theme="light"] .menuNo{color:#0c9bd6;background:#eef1f6;border-color:#d5dce4}
        html[data-theme="light"] .cat-manage{background:rgba(12,155,214,.12);color:#0c9bd6;border-color:rgba(12,155,214,.3)}
        html[data-theme="light"] .cat-data{background:rgba(31,174,107,.12);color:#1fae6b;border-color:rgba(31,174,107,.3)}
        html[data-theme="light"] .cat-drive{background:rgba(217,154,23,.12);color:#b57d0e;border-color:rgba(217,154,23,.3)}
        html[data-theme="light"] .cat-filter{background:rgba(177,74,224,.12);color:#b14ae0;border-color:rgba(177,74,224,.3)}
        html[data-theme="light"] .cat-train{background:rgba(229,72,77,.12);color:#e5484d;border-color:rgba(229,72,77,.3)}
        html[data-theme="light"] .menuName{color:#1a2330}
        html[data-theme="light"] .menuName .favorite{color:#b14ae0}
        html[data-theme="light"] .menuDesc{color:#5b6b7d}
        html[data-theme="light"] .reconnectOverlay{background:rgba(15,23,42,.45)}
        html[data-theme="light"] .reconnectBox{color:#1a2330}
        html[data-theme="light"] .reconnectSpinner{border-color:#d5dce4;border-top-color:#0c9bd6}
        html[data-theme="light"] .reconnectError{color:#e5484d}
        /* DD theme-light 胶囊变体（theme-light.css 重映射值）：
           容器 #f4f6f9 + border #ccd5df + 内描边 #d5dce4，文字 #5b6b7d、
           hover #1a2330；激活态深浅一致（#5cc8ff/#061019/800）无需覆盖 */
        html[data-theme="light"] .langTabs{background:#f4f6f9;border-color:#ccd5df;box-shadow:inset 0 0 0 1px #d5dce4}
        html[data-theme="light"] .langTabs button:not(.active){color:#5b6b7d}
        html[data-theme="light"] .langTabs button:not(.active):hover{color:#1a2330}
        html[data-theme="light"] .langMenu{background:#f4f6f9;border-color:#0c9bd6;box-shadow:0 12px 32px rgba(15,23,42,.16)}
        html[data-theme="light"] .langMenu button{color:#1f3a52}
        html[data-theme="light"] .langMenu button:hover{background:#e8eef5}
        html[data-theme="light"] .langMenu button.active{background:#5cc8ff;color:#061019}
        html[data-theme="light"] .fabToggle{background:#5cc8ff;border-color:#5cc8ff}
        html[data-theme="light"] .fabToggle:hover,html[data-theme="light"] .fabToggle:focus-visible,html[data-theme="light"] .fabToggle:active{background:#3aa8dd;border-color:#3aa8dd}
        html[data-theme="light"] .fabActions .langFab,html[data-theme="light"] .fabActions .helpFab{box-shadow:0 8px 22px rgba(15,23,42,.16)}
        html[data-theme="light"] .helpOverlay{background:rgba(15,23,42,.3)}
        html[data-theme="light"] .helpModal{background:linear-gradient(135deg,#fff,#edf1f6);border-color:#0c9bd6;color:#1f3a52;box-shadow:0 18px 60px rgba(15,23,42,.18)}
        html[data-theme="light"] .helpHead h2{color:#1c2733}
        html[data-theme="light"] .helpClose{color:#6b7280}
        html[data-theme="light"] .helpClose:hover{background:#e5e7eb;color:#111827}
        html[data-theme="light"] .helpSection h3{color:#5b6b7d}
        html[data-theme="light"] .helpList{color:#1f3a52}
    </style>
</head>
<body>
    <div class="container">
        <div class="headerRow">
            <a class="logoLink" href="https://www.donkeydrift.com" target="_blank" rel="noopener"><img class="headerLogo" src="/favicon.png" alt="Donkey"></a>
            <h1>Donkey</h1>
            <a class="ghLink" href="https://github.com/DonkeyDrift/DonkeyDrift" target="_blank" rel="noopener noreferrer" aria-label="DonkeyDrift on GitHub" title="DonkeyDrift on GitHub">
                <svg viewBox="0 0 16 16" width="20" height="20" fill="currentColor" aria-hidden="true"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z"/></svg>
            </a>
            <span class="versionBadge">v{{VERSION}}</span>
            <div class="headerBreak"></div>
            <span class="langTabs" id="themeTabs" title="主题" data-i18n-title="theme.title">
                <button type="button" data-theme="light" data-i18n="theme.light">浅色</button>
                <button type="button" data-theme="system" data-i18n="theme.auto">跟随系统</button>
                <button type="button" data-theme="dark" data-i18n="theme.dark">深色</button>
            </span>
            <span class="langTabs" id="langTabs" title="语言" data-i18n-title="language.title">
                <button type="button" data-lang="zh">中文</button>
                <button type="button" data-lang="en">English</button>
            </span>
        </div>

        <div class="cwdBar">
            <span class="label" data-i18n="cwd.label">当前工作目录</span>
            <span class="path" id="cwd-path">{{CWD}}</span>
        </div>

        <div class="panel">
            <div class="sectionTitle" data-i18n="menu.section">菜单</div>
            <div class="menuGrid" id="menu-grid"></div>
        </div>
    </div>

    <!-- DC FAB 帮助小点（发光小点 + 语言球 + 帮助球） -->
    <button id="fabToggle" class="fabToggle" aria-label="快捷入口" data-i18n-aria="fab.quick"></button>
    <div id="fabActions" class="fabActions">
        <button id="langFab" class="langFab" aria-label="语言" data-i18n-aria="language.title">🌐</button>
        <button id="helpFab" class="helpFab" aria-label="帮助" data-i18n-aria="fab.help">?</button>
    </div>
    <div id="langMenu" class="langMenu">
        <button type="button" data-lang="zh">中文</button>
        <button type="button" data-lang="en">English</button>
    </div>

    <!-- DC 帮助面板 -->
    <div id="helpOverlay" class="helpOverlay"></div>
    <div id="helpModal" class="helpModal" role="dialog" aria-modal="true" aria-labelledby="helpTitle">
        <div class="helpHead">
            <h2 id="helpTitle" data-i18n="help.title">帮助</h2>
            <button class="helpClose" id="helpClose" aria-label="关闭帮助" data-i18n-aria="help.close">×</button>
        </div>
        <section class="helpSection">
            <h3 data-i18n="help.groupKeys">键盘操作</h3>
            <ul class="helpList">
                <li data-i18n="help.keyNumbers">数字键 0-11：选择对应菜单项</li>
            </ul>
        </section>
    </div>

    <!-- DC reconnect overlay -->
    <div class="reconnectOverlay" id="overlay">
        <div class="reconnectBox">
            <div class="reconnectSpinner"></div>
            <div class="reconnectText" id="overlay-text">正在启动 DonkeyDrifter...</div>
            <div class="reconnectError" id="overlay-error"></div>
        </div>
    </div>

    <script>
        // ── i18n（与 DD/DC 同一套 data-i18n 模式与交互） ──
        const LANG_STORAGE_KEY = 'donkeydrifter.ui.lang';
        const THEME_STORAGE_KEY = 'donkeydrifter.ui.theme';

        const I18N = {
            zh: {
                'language.title': '语言',
                'theme.title': '主题',
                'theme.light': '浅色',
                'theme.auto': '跟随系统',
                'theme.dark': '深色',
                'fab.quick': '快捷入口',
                'fab.help': '帮助',
                'cwd.label': '当前工作目录',
                'menu.section': '菜单',
                'menu.favorite': '「常用」',
                'help.title': '帮助',
                'help.close': '关闭帮助',
                'help.groupKeys': '键盘操作',
                'help.keyNumbers': '数字键 0-11：选择对应菜单项',
                'overlay.findingDc': '正在查找 Drifter Console...',
                'overlay.dcNotFound': '未找到 Drifter Console（请确认车辆已开机并联网）',
                'overlay.starting': '正在启动 DonkeyDrifter...',
                'overlay.startingKimiWeb': '正在启动 Kimi Code Web（kimi 启动较慢，请耐心等待）...',
                'overlay.failed': '启动失败',
                'overlay.success': '启动成功！正在跳转...',
                'overlay.slow': '前端服务启动较慢，正在跳转...',
                'overlay.networkError': '网络错误',
                'overlay.unknownError': '未知错误',
                'overlay.notImplemented': '该功能暂未在浏览器中实现，请使用终端',
            },
            en: {
                'language.title': 'Language',
                'theme.title': 'Theme',
                'theme.light': 'Light',
                'theme.auto': 'Auto',
                'theme.dark': 'Dark',
                'fab.quick': 'Quick actions',
                'fab.help': 'Help',
                'cwd.label': 'Current Working Directory',
                'menu.section': 'Menu',
                'menu.favorite': '「Common」',
                'help.title': 'Help',
                'help.close': 'Close help',
                'help.groupKeys': 'Keyboard',
                'help.keyNumbers': 'Number keys 0-11: select the corresponding menu item',
                'overlay.findingDc': 'Locating Drifter Console...',
                'overlay.dcNotFound': 'Drifter Console not found (make sure the car is powered on and connected)',
                'overlay.starting': 'Starting DonkeyDrifter...',
                'overlay.startingKimiWeb': 'Starting Kimi Code Web (kimi starts slowly, please wait)...',
                'overlay.failed': 'Launch failed',
                'overlay.success': 'Started! Redirecting...',
                'overlay.slow': 'Frontend is slow to start, redirecting...',
                'overlay.networkError': 'Network error',
                'overlay.unknownError': 'Unknown error',
                'overlay.notImplemented': 'This feature is not available in the browser yet; please use the terminal',
            },
        };

        let uiLang = 'zh';
        let uiTheme = 'system';

        function normalizeLanguage(lang) { return lang === 'en' ? 'en' : 'zh'; }
        // 浏览器语言自动检测（zh* → 中文，其余 → 英文），仅在没有显式存储选择时生效；
        // 一旦用户手动切换，localStorage 中的显式选择优先并跨重启保持（与 DD web_ui 同语义）
        function detectBrowserLanguage() {
            try { return String(navigator.language || '').toLowerCase().indexOf('zh') === 0 ? 'zh' : 'en'; }
            catch (e) { return 'zh'; }
        }
        function readStoredLanguage() {
            try {
                const v = localStorage.getItem(LANG_STORAGE_KEY);
                if (v === 'zh' || v === 'en') return v;
            } catch (e) {}
            return detectBrowserLanguage();
        }
        function t(key) {
            return (I18N[uiLang] && I18N[uiLang][key]) || I18N.zh[key] || key;
        }
        function applyLanguage(lang) {
            uiLang = normalizeLanguage(lang);
            document.documentElement.lang = uiLang === 'zh' ? 'zh-CN' : 'en';
            document.querySelectorAll('[data-i18n]').forEach(function(el) {
                el.textContent = t(el.dataset.i18n);
            });
            document.querySelectorAll('[data-i18n-aria]').forEach(function(el) {
                el.setAttribute('aria-label', t(el.dataset.i18nAria));
            });
            document.querySelectorAll('[data-i18n-title]').forEach(function(el) {
                el.title = t(el.dataset.i18nTitle);
            });
            document.querySelectorAll('[data-lang]').forEach(function(b) {
                b.classList.toggle('active', b.dataset.lang === uiLang);
            });
            renderMenu();
        }
        function setLanguage(lang) {
            try { localStorage.setItem(LANG_STORAGE_KEY, normalizeLanguage(lang)); } catch (e) {}
            applyLanguage(lang);
            closeLanguageMenu();
        }

        // ── 主题：浅色 / 跟随系统 / 深色（默认跟随系统，选中 system 时经 matchMedia 实时解析并监听） ──
        function systemTheme() {
            try {
                return window.matchMedia('(prefers-color-scheme: light)').matches
                    ? 'light' : 'dark';
            } catch (e) { return 'dark'; }
        }
        function renderThemeTabs() {
            document.querySelectorAll('#themeTabs button[data-theme]').forEach(function(b) {
                b.classList.toggle('active', b.dataset.theme === uiTheme);
            });
        }
        function applyTheme(mode) {
            uiTheme = (mode === 'light' || mode === 'dark') ? mode : 'system';
            document.documentElement.dataset.theme =
                uiTheme === 'system' ? systemTheme() : uiTheme;
            renderThemeTabs();
        }
        function setTheme(mode) {
            try { localStorage.setItem(THEME_STORAGE_KEY, mode); } catch (e) {}
            applyTheme(mode);
        }
        function initTheme() {
            var stored = 'system';
            try {
                var s = localStorage.getItem(THEME_STORAGE_KEY);
                if (s === 'light' || s === 'dark' || s === 'system') stored = s;
            } catch (e) {}
            applyTheme(stored);
            try {
                var mq = window.matchMedia('(prefers-color-scheme: light)');
                var onChange = function() { if (uiTheme === 'system') applyTheme('system'); };
                if (mq.addEventListener) mq.addEventListener('change', onChange);
                else if (mq.addListener) mq.addListener(onChange);
            } catch (e) {}
        }

        // ── DC FAB 帮助小点 ──
        function toggleFabActions(e) {
            if (e) e.stopPropagation();
            document.getElementById('fabActions').classList.toggle('show');
        }
        function collapseFabActions() {
            document.getElementById('fabActions').classList.remove('show');
            closeLanguageMenu();
        }
        function toggleLanguageMenu(e) {
            if (e) e.stopPropagation();
            document.getElementById('fabActions').classList.add('show');
            document.getElementById('langMenu').classList.toggle('show');
        }
        function closeLanguageMenu() {
            document.getElementById('langMenu').classList.remove('show');
        }
        function openHelpModal() {
            document.getElementById('fabActions').classList.add('show');
            closeLanguageMenu();
            document.getElementById('helpOverlay').classList.add('show');
            document.getElementById('helpModal').classList.add('show');
        }
        function closeHelpModal() {
            document.getElementById('helpOverlay').classList.remove('show');
            document.getElementById('helpModal').classList.remove('show');
        }

        // 菜单项数据（条目与 tui.py 保持一致，desc/catLabel 双语；
        // 网页版 0 号为 Drifter Console 置顶，编号/顺序与 TUI 不同）
        const menuItems = [
            {no: 0,  cat: "drive",  name: "Drifter Console", descZh: "打开 Drifter Console",               descEn: "Open Drifter Console",                           favorite: true},
            {no: 1,  cat: "manage", name: "Create Car",   descZh: "创建新的 DonkeyCar 项目",                descEn: "Create a new DonkeyCar project",                 favorite: false},
            {no: 2,  cat: "manage", name: "Open",         descZh: "打开已有 DonkeyCar 项目",                descEn: "Open an existing DonkeyCar project",             favorite: false},
            {no: 3,  cat: "data",   name: "Clear Data",   descZh: "清空当前项目 data 目录",                 descEn: "Clear the current project's data directory",     favorite: false},
            {no: 4,  cat: "data",   name: "Backup Data",  descZh: "备份当前项目 data 目录",                 descEn: "Back up the current project's data directory",   favorite: false},
            {no: 5,  cat: "data",   name: "Restore Data", descZh: "从备份恢复 data 目录",                   descEn: "Restore the data directory from a backup",       favorite: false},
            {no: 6,  cat: "drive",  name: "Drive",        descZh: "打开 Web Console 驾驶控制台",            descEn: "Open the Web Console driving console",           favorite: true},
            {no: 7,  cat: "filter", name: "Web",          descZh: "启动 Web UI（前后端）",                  descEn: "Start the Web UI (frontend + backend)",          favorite: true},
            {no: 8,  cat: "filter", name: "Donkey UI",    descZh: "启动数据筛选工具（Windows下需要WSL来运行）", descEn: "Start the data filtering tool (requires WSL on Windows)", favorite: true},
            {no: 9,  cat: "train",  name: "Train Local",  descZh: "本地训练",                               descEn: "Train locally",                                favorite: true},
            {no: 10, cat: "train",  name: "Train Online", descZh: "云端训练（train_online.conf）",          descEn: "Cloud training (train_online.conf)",             favorite: true},
            {no: 11, cat: "manage", name: "Kimi Code Web", descZh: "打开 Kimi Code Web",                    descEn: "Open Kimi Code Web",                             favorite: true},
        ];
        const catLabels = {
            manage: {zh: "管理", en: "Manage"},
            data:   {zh: "数据", en: "Data"},
            drive:  {zh: "驾驶", en: "Drive"},
            filter: {zh: "筛选", en: "Filter"},
            train:  {zh: "训练", en: "Train"},
        };

        let selectedNo = null;
        let pendingDigit1 = null;

        // 渲染菜单（DC state card 风格）
        function renderMenu() {
            const grid = document.getElementById('menu-grid');
            grid.innerHTML = '';
            menuItems.forEach(item => {
                const div = document.createElement('div');
                div.className = 'menuItem';
                div.dataset.no = item.no;
                div.onclick = () => selectItem(item.no);
                const favMark = item.favorite
                    ? ' <span class="favorite">' + t('menu.favorite') + '</span>' : '';
                const catLabel = catLabels[item.cat][uiLang];
                const desc = uiLang === 'en' ? item.descEn : item.descZh;
                div.innerHTML =
                    '<div class="menuNo">' + item.no + '</div>' +
                    '<div class="catPill cat-' + item.cat + '">' + catLabel + '</div>' +
                    '<div class="menuContent">' +
                        '<div class="menuName">' + item.name + favMark + '</div>' +
                        '<div class="menuDesc">' + desc + '</div>' +
                    '</div>';
                grid.appendChild(div);
            });
        }

        // 高亮选中项
        function highlightRow(no) {
            document.querySelectorAll('#menu-grid .menuItem').forEach(el => {
                el.classList.toggle(
                    'selected', parseInt(el.dataset.no) === no
                );
            });
            selectedNo = no;
        }

        // 选择菜单项
        function selectItem(no) {
            highlightRow(no);
            const item = menuItems.find(m => m.no === no);
            if (!item) return;

            if (no === 0) {
                openDrifterConsole();
            } else if (no === 6) {
                launchDrive();
            } else if (no === 11) {
                launchKimiCodeWeb();
            } else {
                showError(t('overlay.notImplemented'));
            }
        }

        // 打开 Drifter Console（ESP32 Web Console，服务端局域网发现）
        async function openDrifterConsole() {
            const overlay = document.getElementById('overlay');
            const overlayText = document.getElementById('overlay-text');
            const overlayError = document.getElementById('overlay-error');
            overlay.classList.add('show');
            overlayText.textContent = t('overlay.findingDc');
            overlayError.textContent = '';

            try {
                const resp = await fetch('/api/launch/dc', {
                    method: 'POST'
                });
                const data = await resp.json();
                if (data.status === 'ok' && data.url) {
                    overlayText.textContent = t('overlay.success');
                    window.location.href = data.url;
                } else {
                    showError(t('overlay.dcNotFound'));
                }
            } catch (e) {
                showError(t('overlay.networkError') + ': ' + e.message);
            }
        }

        // 启动驾驶
        async function launchDrive() {
            const overlay = document.getElementById('overlay');
            const overlayText = document.getElementById('overlay-text');
            const overlayError = document.getElementById('overlay-error');
            overlay.classList.add('show');
            overlayText.textContent = t('overlay.starting');
            overlayError.textContent = '';

            try {
                const resp = await fetch('/api/launch/drive', {
                    method: 'POST'
                });
                const data = await resp.json();

                if (data.status === 'launched' ||
                    data.status === 'already_running') {
                    const url = data.url.replace(
                        'localhost', window.location.hostname
                    );
                    // 轮询等待前端 vite 就绪后再跳转（最多 30 次 × 1s = 30s）
                    var ready = false;
                    for (var i = 0; i < 30; i++) {
                        try {
                            await fetch(url, {mode: 'no-cors'});
                            ready = true;
                            break;
                        } catch (e) {
                            overlayText.textContent =
                                t('overlay.starting') + ' (' + (i + 1) + '/30)';
                            await new Promise(function(res) {
                                setTimeout(res, 1000);
                            });
                        }
                    }
                    if (ready) {
                        overlayText.textContent = t('overlay.success');
                        window.location.href = url;
                    } else {
                        overlayText.textContent = t('overlay.slow');
                        setTimeout(function() {
                            window.location.href = url;
                        }, 1000);
                    }
                } else if (data.status === 'error') {
                    overlayText.textContent = t('overlay.failed');
                    overlayError.textContent =
                        data.error || t('overlay.unknownError');
                    setTimeout(function() {
                        overlay.classList.remove('show');
                    }, 3000);
                }
            } catch (e) {
                overlayText.textContent = t('overlay.failed');
                overlayError.textContent =
                    t('overlay.networkError') + ': ' + e.message;
                setTimeout(function() {
                    overlay.classList.remove('show');
                }, 3000);
            }
        }

        // 打开 Kimi Code Web（菜单 11 号）：POST /api/launch/kimi-code-web，
        // cwd 固定 /home/dkc/projects（issue 要求先进入 projects 主文件夹再
        // 执行 kimi；目录不存在服务端会报错）。kimi 冷启动可达数十秒，
        // 服务端整体超时 120s，浏览器 fetch 默认无超时、耐心等待即可；
        // 拿到 URL 后当前标签页跳转。
        async function launchKimiCodeWeb() {
            const overlay = document.getElementById('overlay');
            const overlayText = document.getElementById('overlay-text');
            const overlayError = document.getElementById('overlay-error');
            overlay.classList.add('show');
            overlayText.textContent = t('overlay.startingKimiWeb');
            overlayError.textContent = '';

            try {
                const resp = await fetch('/api/launch/kimi-code-web', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({cwd: '/home/dkc/projects'})
                });
                const data = await resp.json();
                if (resp.ok && data.status === 'ok' && data.url) {
                    overlayText.textContent = t('overlay.success');
                    window.location.href = data.url;
                } else {
                    overlayText.textContent = t('overlay.failed');
                    overlayError.textContent =
                        data.error || t('overlay.unknownError');
                    setTimeout(function() {
                        overlay.classList.remove('show');
                    }, 3000);
                }
            } catch (e) {
                overlayText.textContent = t('overlay.failed');
                overlayError.textContent =
                    t('overlay.networkError') + ': ' + e.message;
                setTimeout(function() {
                    overlay.classList.remove('show');
                }, 3000);
            }
        }

        // 显示错误提示
        function showError(msg) {
            const overlay = document.getElementById('overlay');
            const overlayText = document.getElementById('overlay-text');
            const overlayError = document.getElementById('overlay-error');
            overlay.classList.add('show');
            overlayText.textContent = '';
            overlayError.textContent = msg;
            setTimeout(function() {
                overlay.classList.remove('show');
            }, 2500);
        }

        // 键盘事件
        document.addEventListener('keydown', function(e) {
            const key = e.key;

            // ESC 关闭弹窗
            if (key === 'Escape') {
                closeHelpModal();
                document.getElementById('overlay')
                    .classList.remove('show');
                return;
            }

            // 帮助面板打开时，仅响应 ? 和 0 关闭
            if (document.getElementById('helpModal')
                .classList.contains('show')) {
                if (key === '?' || key === '0') {
                    closeHelpModal();
                }
                return;
            }

            // 遮罩打开时不处理菜单导航
            if (document.getElementById('overlay')
                .classList.contains('show')) {
                return;
            }

            // 处理 "10"/"11" 输入：先按 1，400ms 内按 0 选中 10、再按 1 选中 11
            if (pendingDigit1 !== null) {
                clearTimeout(pendingDigit1.timer);
                pendingDigit1 = null;
                if (key === '0') {
                    selectItem(10);
                    return;
                }
                if (key === '1') {
                    selectItem(11);
                    return;
                }
            }

            if (key === '1') {
                pendingDigit1 = {
                    timer: setTimeout(function() {
                        pendingDigit1 = null;
                        selectItem(1);
                    }, 400)
                };
            } else if (key >= '2' && key <= '9') {
                selectItem(parseInt(key));
            } else if (key === '0') {
                selectItem(0);
            } else if (key === '?') {
                openHelpModal();
            }
        });

        // 页面加载时获取状态
        async function fetchStatus() {
            try {
                const resp = await fetch('/api/status');
                const data = await resp.json();
                if (data.project) {
                    document.getElementById('cwd-path').textContent =
                        data.project;
                }
            } catch (e) {
                // 忽略错误，使用默认路径
            }
        }

        // 控件事件绑定
        document.getElementById('fabToggle')
            .addEventListener('click', toggleFabActions);
        document.getElementById('langFab')
            .addEventListener('click', toggleLanguageMenu);
        document.getElementById('helpFab')
            .addEventListener('click', function(e) {
                if (e) e.stopPropagation();
                openHelpModal();
            });
        document.getElementById('helpOverlay')
            .addEventListener('click', closeHelpModal);
        document.getElementById('helpClose')
            .addEventListener('click', closeHelpModal);
        document.querySelectorAll('[data-lang]').forEach(function(b) {
            b.addEventListener('click', function() {
                setLanguage(b.dataset.lang);
            });
        });
        document.querySelectorAll('#themeTabs button[data-theme]')
            .forEach(function(b) {
                b.addEventListener('click', function() {
                    setTheme(b.dataset.theme);
                });
            });
        document.addEventListener('click', collapseFabActions);
        window.addEventListener('scroll', collapseFabActions, {passive: true});
        window.addEventListener('touchmove', collapseFabActions, {passive: true});

        // 初始化
        initTheme();
        applyLanguage(readStoredLanguage());
        fetchStatus();
        // 检测 #drive hash 自动启动 DonkeyDrifter
        if (location.hash === '#drive') {
            launchDrive();
        }
    </script>
</body>
</html>"""
