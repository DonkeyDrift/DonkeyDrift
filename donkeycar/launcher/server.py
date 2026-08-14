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


# ── PID 文件管理（与 tui.py / base.py 保持一致） ────────────────────────

_DRIVE_PID_FILE = Path.home() / ".donkeycar" / "drive.pid"

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


def _read_drive_pid_file():
    """读取上次 donkey drive 记录的进程 PID 列表。"""
    if not _DRIVE_PID_FILE.exists():
        return []
    try:
        with open(_DRIVE_PID_FILE, "r") as f:
            return [int(line.strip()) for line in f if line.strip()]
    except Exception:
        return []


def _write_drive_pid_file(pids):
    """将当前 donkey drive 启动的进程 PID 写入记录文件。"""
    _DRIVE_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_DRIVE_PID_FILE, "w") as f:
        for pid in pids:
            f.write(f"{pid}\n")


def _remove_drive_pid_file():
    """删除 PID 记录文件。"""
    try:
        _DRIVE_PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def _kill_previous_drive_processes():
    """读取 PID 文件，精确杀掉上一次 donkey drive 启动的进程。"""
    pids = _read_drive_pid_file()
    if not pids:
        return
    # 先发送 SIGTERM 优雅终止
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    # 等待 0.5 秒让进程退出
    threading.Event().wait(0.5)
    # 对仍存活的进程发送 SIGKILL 强制终止
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    _remove_drive_pid_file()


def _kill_orphaned_donkey_processes():
    """通过进程名搜索并杀掉所有 donkey web 和 manage.py drive 进程。

    作为 PID 文件方式的补充，处理未通过正常流程启动的孤儿进程
    （如用户直接在终端运行 donkey web 而未写入 PID 文件，
    或多次启动导致旧进程未被追踪）。
    """
    for pattern in ["donkey web", "manage.py drive"]:
        try:
            subprocess.run(
                ["pkill", "-f", pattern],
                capture_output=True, timeout=5,
            )
        except Exception:
            pass
    # 等待进程退出
    threading.Event().wait(0.5)
    # SIGKILL 仍存活的进程
    for pattern in ["donkey web", "manage.py drive"]:
        try:
            subprocess.run(
                ["pkill", "-9", "-f", pattern],
                capture_output=True, timeout=5,
            )
        except Exception:
            pass


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

    每次调用都会先杀掉上一次的 donkey drive 进程（通过 PID 文件追踪），
    然后启动新的进程。这确保不会出现硬件资源冲突（如摄像头占用）。
    """
    with _proc_lock:
        # 杀掉上一次的进程（通过 PID 文件追踪，包括终端和 Launcher 启动的）
        _kill_previous_drive_processes()
        # 兜底：通过进程名搜索杀掉所有 donkey web / manage.py drive 孤儿进程
        _kill_orphaned_donkey_processes()
        # 清理 launcher 自己跟踪的进程引用
        for key in ("web", "car"):
            _processes[key] = None
        _processes["backend_port"] = None
        _processes["frontend_port"] = None

        # 查找 mycar 项目
        project_path = _find_mycar_project()
        if project_path is None:
            return {
                "status": "error",
                "error": "未找到有效的 mycar 项目"
                         "（需包含 manage.py 和 myconfig.py）",
            }

        # 选择可用端口
        backend_port = _choose_available_backend_port(8100)
        frontend_port = _choose_available_backend_port(5188)

        # 获取 Web UI 路径
        web_ui_path = _get_bundled_web_ui_path()

        # 构建 web 命令（不添加 --open，由 launcher 负责重定向浏览器）
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
        creationflags = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            if sys.platform == "win32" else 0
        )

        try:
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

        # 写入 PID 文件
        _write_drive_pid_file([web_proc.pid, car_proc.pid])

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
    """获取当前进程状态。"""
    with _proc_lock:
        web_proc = _processes["web"]
        car_proc = _processes["car"]
        running = web_proc is not None and web_proc.poll() is None
        frontend_port = _processes["frontend_port"]
        backend_port = _processes["backend_port"]
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

def _get_local_ip():
    """获取本机在局域网中的 IP 地址（排除 VPN/TUN 接口）。"""
    try:
        result = subprocess.check_output(
            ["hostname", "-I"], text=True, stderr=subprocess.DEVNULL
        ).strip()
        ips = result.split()
        # 优先选择 192.168.x.x（局域网）
        for ip in ips:
            if ip.startswith("192.168."):
                return ip
        # 回退到第一个非 VPN/loopback 的 IP
        for ip in ips:
            if (not ip.startswith("127.") and
                    not ip.startswith("198.18.")):
                return ip
    except Exception:
        pass
    return None


def _report_hostip_to_esp32():
    """通过串口向 ESP32 报告本机 IP。"""
    local_ip = _get_local_ip()
    if not local_ip:
        return
    # 尝试常见串口设备
    for port in ["/dev/ttyACM0", "/dev/ttyACM1", "/dev/ttyUSB0"]:
        try:
            with open(port, 'w') as f:
                f.write(f"HOSTIP|{local_ip}\n")
                f.flush()
            break  # 成功写入一个即可
        except (OSError, IOError):
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
        else:
            self._serve_json({"error": "not found"}, code=404)

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

    def _serve_json(self, data, code=200):
        """提供 JSON 响应。"""
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header(
            "Content-Type", "application/json; charset=utf-8"
        )
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
(async function(){
  try{
    var r=await fetch('/api/launch/drive',{method:'POST'});
    var d=await r.json();
    if(d.status==='launched'){
      var url=d.url.replace('localhost',window.location.hostname);
      window.location.href=url;
    }else{
      document.getElementById('spinner').style.display='none';
      document.getElementById('text').textContent='启动失败';
      document.getElementById('error').textContent=d.error||'未知错误';
    }
  }catch(e){
    document.getElementById('spinner').style.display='none';
    document.getElementById('text').textContent='启动失败';
    document.getElementById('error').textContent='网络错误: '+e.message;
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
    // 首屏防闪烁：渲染前应用持久化主题（与 DD/DC 同一模式，"跟随系统"经 matchMedia 实时解析）
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

        /* DC headerRow */
        .headerRow{display:flex;align-items:flex-end;gap:12px;flex-wrap:wrap;margin:0 0 10px}
        .headerLogo{width:32px;height:32px;border-radius:8px;border:1px solid #2b3441;align-self:center}
        .headerRow h1{font-size:22px;margin:0}
        .version{color:#8fa1b5;font-size:12px;text-transform:uppercase;letter-spacing:.08em;display:inline-block;transform:translateY(-1px)}
        /* DD GitHubLink / VersionBadge */
        .ghLink{display:inline-flex;align-items:center;color:#8fa1b5;transform:translateY(-1px)}
        .ghLink:hover{color:#5cc8ff}
        .versionBadge{color:#6b7d90;font-size:12px;text-transform:uppercase;letter-spacing:.05em;display:inline-block;transform:translateY(-1px)}

        /* DC langTabs（顶栏主题/语言分段控件，逐字对齐 WebConsoleAssets.h） */
        .langTabs{display:inline-flex;align-items:center;gap:2px;background:#171c24;border:none;border-radius:999px;padding:0 2px;height:24px;box-sizing:border-box;box-shadow:inset 0 0 0 1px #2b3441}
        .langTabs button{padding:0 10px;height:24px;min-width:0;border:none;border-radius:999px;background:transparent;color:#8fa1b5;font-size:11px;font-weight:800;line-height:1;cursor:pointer}
        .langTabs button:hover{background:#222b36;color:#e8f6ff}
        .langTabs button.active{background:#5cc8ff;color:#061019}
        .langTabs button.active:hover{background:#8bdcff;color:#061019}
        #themeTabs{margin-left:auto}

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
        html[data-theme="light"] .version{color:#5b6b7d}
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
        html[data-theme="light"] .langTabs{background:#dde3ec;box-shadow:inset 0 0 0 1px #aeb9c7}
        html[data-theme="light"] .langTabs button{background:transparent;color:#5b6b7d}
        html[data-theme="light"] .langTabs button:hover{background:#d3dce6;color:#0b2536}
        html[data-theme="light"] .langTabs button.active{background:#5cc8ff;color:#061019}
        html[data-theme="light"] .langTabs button.active:hover{background:#8bdcff;color:#061019}
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
            <img class="headerLogo" src="/favicon.png" alt="Donkey">
            <h1>Donkey</h1>
            <span class="version">DonkeyDrifter Web Launcher</span>
            <a class="ghLink" href="https://github.com/DonkeyDrift/DonkeyDrift" target="_blank" rel="noopener noreferrer" aria-label="DonkeyDrift on GitHub" title="DonkeyDrift on GitHub">
                <svg viewBox="0 0 16 16" width="20" height="20" fill="currentColor" aria-hidden="true"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z"/></svg>
            </a>
            <span class="versionBadge">v{{VERSION}}</span>
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
            <span class="label">CWD</span>
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
                <li data-i18n="help.keyNumbers">数字键 1-10：选择对应菜单项</li>
                <li data-i18n="help.keyQuestion">?：显示此帮助信息</li>
                <li data-i18n="help.keyZero">0：返回上一页</li>
                <li data-i18n="help.keyEsc">ESC：关闭弹窗</li>
            </ul>
        </section>
        <section class="helpSection">
            <h3 data-i18n="help.groupNotes">说明</h3>
            <ul class="helpList">
                <li data-i18n="help.noteFavorite">带 [*] 标记的为常用功能</li>
                <li data-i18n="help.noteDrive">目前仅支持通过浏览器启动「驾驶」功能（选项 6）</li>
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
                'menu.section': '菜单',
                'help.title': '帮助',
                'help.close': '关闭帮助',
                'help.groupKeys': '键盘操作',
                'help.keyNumbers': '数字键 1-10：选择对应菜单项',
                'help.keyQuestion': '?：显示此帮助信息',
                'help.keyZero': '0：返回上一页',
                'help.keyEsc': 'ESC：关闭弹窗',
                'help.groupNotes': '说明',
                'help.noteFavorite': '带 [*] 标记的为常用功能',
                'help.noteDrive': '目前仅支持通过浏览器启动「驾驶」功能（选项 6）',
                'overlay.starting': '正在启动 DonkeyDrifter...',
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
                'menu.section': 'Menu',
                'help.title': 'Help',
                'help.close': 'Close help',
                'help.groupKeys': 'Keyboard',
                'help.keyNumbers': 'Number keys 1-10: select the corresponding menu item',
                'help.keyQuestion': '?: show this help',
                'help.keyZero': '0: go back',
                'help.keyEsc': 'ESC: close dialogs',
                'help.groupNotes': 'Notes',
                'help.noteFavorite': 'Items marked [*] are favorites',
                'help.noteDrive': 'Only "Drive" (option 6) can be launched from the browser for now',
                'overlay.starting': 'Starting DonkeyDrifter...',
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
        function readStoredLanguage() {
            try { return normalizeLanguage(localStorage.getItem(LANG_STORAGE_KEY)); }
            catch (e) { return 'zh'; }
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

        // ── 主题：浅色 / 跟随系统 / 深色（system 经 matchMedia 实时解析并监听） ──
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

        // 菜单项数据（与 tui.py 保持一致，desc/catLabel 双语）
        const menuItems = [
            {no: 1,  cat: "manage", name: "createcar",    descZh: "创建新的 DonkeyCar 项目",                descEn: "Create a new DonkeyCar project",                 favorite: true},
            {no: 2,  cat: "manage", name: "open",         descZh: "打开已有 DonkeyCar 项目",                descEn: "Open an existing DonkeyCar project",             favorite: false},
            {no: 3,  cat: "data",   name: "clear_data",   descZh: "清空当前项目 data 目录",                 descEn: "Clear the current project's data directory",     favorite: true},
            {no: 4,  cat: "data",   name: "backup_data",  descZh: "备份当前项目 data 目录",                 descEn: "Back up the current project's data directory",   favorite: false},
            {no: 5,  cat: "data",   name: "restore_data", descZh: "从备份恢复 data 目录",                   descEn: "Restore the data directory from a backup",       favorite: false},
            {no: 6,  cat: "drive",  name: "drive",        descZh: "打开 Web Console 驾驶控制台",            descEn: "Open the Web Console driving console",           favorite: true},
            {no: 7,  cat: "filter", name: "web",          descZh: "启动 Web UI（前后端）",                  descEn: "Start the Web UI (frontend + backend)",          favorite: true},
            {no: 8,  cat: "filter", name: "donkey_ui",    descZh: "启动数据筛选工具（Windows下需要WSL来运行）", descEn: "Start the data filtering tool (requires WSL on Windows)", favorite: false},
            {no: 9,  cat: "train",  name: "train_local",  descZh: "本地训练",                               descEn: "Train locally",                                favorite: false},
            {no: 10, cat: "train",  name: "train_online", descZh: "云端训练（train_online.conf）",          descEn: "Cloud training (train_online.conf)",             favorite: true},
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
                    ? ' <span class="favorite">[*]</span>' : '';
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

            if (no === 6) {
                launchDrive();
            } else {
                showError(t('overlay.notImplemented'));
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

            // 处理 "10" 输入：先按 1，400ms 内按 0 则选中 10
            if (pendingDigit1 !== null) {
                clearTimeout(pendingDigit1.timer);
                pendingDigit1 = null;
                if (key === '0') {
                    selectItem(10);
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
                if (document.referrer) {
                    history.back();
                } else {
                    window.close();
                }
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
