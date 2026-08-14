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


# ── PID 文件管理（与 tui.py / base.py 保持一致） ────────────────────────

_DRIVE_PID_FILE = Path.home() / ".donkeycar" / "drive.pid"


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
        elif path in ("/favicon.png", "/favicon.ico"):
            self._serve_favicon()
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
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_favicon(self):
        """提供 Donkey favicon 图标。"""
        favicon_path = Path(__file__).parent / "donkey_favicon.png"
        if favicon_path.exists():
            body = favicon_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Cache-Control", "no-cache")
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
<link rel="icon" type="image/png" href="/favicon.png?v=2">
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
    <link rel="icon" type="image/png" href="/favicon.png?v=2">
    <title>Donkey</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
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

        /* Footer hint */
        .footerHint{margin-top:12px;text-align:center;font-size:12px;color:#8fa1b5}
        .footerHint .key{color:#5cc8ff;background:rgba(92,200,255,.1);padding:2px 8px;border-radius:999px;margin:0 2px;font-weight:700}

        /* DC reconnect overlay */
        .reconnectOverlay{position:fixed;inset:0;background:rgba(16,19,24,.88);display:none;align-items:center;justify-content:center;z-index:100}
        .reconnectOverlay.show{display:flex}
        .reconnectBox{text-align:center;color:#e8edf2}
        .reconnectSpinner{width:48px;height:48px;border:4px solid #2b3441;border-top-color:#5cc8ff;border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 16px}
        .reconnectText{font-size:16px;line-height:1.6}
        .reconnectError{color:#ff6b6b;margin-top:8px;font-size:14px}
        @keyframes spin{to{transform:rotate(360deg)}}

        /* DC dialog (help modal) */
        .modal{position:fixed;inset:0;display:none;align-items:center;justify-content:center;background:rgba(5,7,10,.72);z-index:10}
        .modal.show{display:flex}
        .dialog{width:min(420px,calc(100vw - 28px));background:linear-gradient(135deg,#1c2430,#121821);border:1px solid #ffcc66;border-radius:14px;padding:18px;box-shadow:0 18px 60px rgba(0,0,0,.45)}
        .dialog h2{margin:0 0 8px;font-size:20px;color:#ffcc66}
        .dialog p{color:#b7c6d8;font-size:14px;line-height:1.5;margin-bottom:6px}
        .dialogActions{display:flex;gap:8px;justify-content:flex-end;margin-top:14px}
        .dialogBtn{background:#5cc8ff;color:#061019;border:1px solid #5cc8ff;border-radius:999px;padding:6px 16px;font-weight:700;font-size:12px;cursor:pointer}
        .dialogBtn:hover{background:#8bdcff}
    </style>
</head>
<body>
    <div class="container">
        <div class="headerRow">
            <img class="headerLogo" src="/favicon.png?v=2" alt="Donkey">
            <h1>Donkey</h1>
            <span class="version">DonkeyDrifter Web Launcher</span>
        </div>

        <div class="cwdBar">
            <span class="label">CWD</span>
            <span class="path" id="cwd-path">{{CWD}}</span>
        </div>

        <div class="panel">
            <div class="sectionTitle">菜单</div>
            <div class="menuGrid" id="menu-grid"></div>
        </div>

        <div class="footerHint">
            输入<span class="key">编号</span>选择功能，<span class="key">?</span>帮助，<span class="key">0</span>退出
        </div>
    </div>

    <!-- DC reconnect overlay -->
    <div class="reconnectOverlay" id="overlay">
        <div class="reconnectBox">
            <div class="reconnectSpinner"></div>
            <div class="reconnectText" id="overlay-text">正在启动 DonkeyDrifter...</div>
            <div class="reconnectError" id="overlay-error"></div>
        </div>
    </div>

    <!-- DC dialog (help) -->
    <div class="modal" id="help-modal">
        <div class="dialog">
            <h2>帮助</h2>
            <p><span style="color:#5cc8ff">数字键 1-10</span> 选择对应菜单项</p>
            <p><span style="color:#5cc8ff">?</span> 显示此帮助信息</p>
            <p><span style="color:#5cc8ff">0</span> 返回上一页</p>
            <p><span style="color:#5cc8ff">ESC</span> 关闭弹窗</p>
            <p style="margin-top:8px;color:#8fa1b5;">带 <span style="color:#d96bff">[*]</span> 标记的为常用功能</p>
            <p style="color:#8fa1b5;">目前仅支持通过浏览器启动「驾驶」功能 (选项 6)</p>
            <div class="dialogActions">
                <button class="dialogBtn" onclick="hideHelp()">关闭</button>
            </div>
        </div>
    </div>

    <script>
        // 菜单项数据（与 tui.py 保持一致）
        const menuItems = [
            {no: 1,  cat: "manage", catLabel: "管理", name: "createcar",    desc: "创建新的 DonkeyCar 项目",                    favorite: true},
            {no: 2,  cat: "manage", catLabel: "管理", name: "open",         desc: "打开已有 DonkeyCar 项目",                    favorite: false},
            {no: 3,  cat: "data",   catLabel: "数据", name: "clear_data",   desc: "清空当前项目 data 目录",                     favorite: true},
            {no: 4,  cat: "data",   catLabel: "数据", name: "backup_data",  desc: "备份当前项目 data 目录",                     favorite: false},
            {no: 5,  cat: "data",   catLabel: "数据", name: "restore_data", desc: "从备份恢复 data 目录",                       favorite: false},
            {no: 6,  cat: "drive",  catLabel: "驾驶", name: "drive",        desc: "打开 Web Console 驾驶控制台",                 favorite: true},
            {no: 7,  cat: "filter", catLabel: "筛选", name: "web",          desc: "启动 Web UI（前后端）",                      favorite: true},
            {no: 8,  cat: "filter", catLabel: "筛选", name: "donkey_ui",    desc: "启动数据筛选工具（Windows下需要WSL来运行）", favorite: false},
            {no: 9,  cat: "train",  catLabel: "训练", name: "train_local",  desc: "本地训练",                                    favorite: false},
            {no: 10, cat: "train",  catLabel: "训练", name: "train_online", desc: "云端训练（train_online.conf）",              favorite: true},
        ];

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
                div.innerHTML =
                    '<div class="menuNo">' + item.no + '</div>' +
                    '<div class="catPill cat-' + item.cat + '">' + item.catLabel + '</div>' +
                    '<div class="menuContent">' +
                        '<div class="menuName">' + item.name + favMark + '</div>' +
                        '<div class="menuDesc">' + item.desc + '</div>' +
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
                showError('该功能暂未在浏览器中实现，请使用终端');
            }
        }

        // 启动驾驶
        async function launchDrive() {
            const overlay = document.getElementById('overlay');
            const overlayText = document.getElementById('overlay-text');
            const overlayError = document.getElementById('overlay-error');
            overlay.classList.add('show');
            overlayText.textContent = '正在启动 DonkeyDrifter...';
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
                                '正在启动 DonkeyDrifter... (' + (i + 1) + '/30)';
                            await new Promise(function(res) {
                                setTimeout(res, 1000);
                            });
                        }
                    }
                    if (ready) {
                        overlayText.textContent = '启动成功！正在跳转...';
                        window.location.href = url;
                    } else {
                        overlayText.textContent =
                            '前端服务启动较慢，正在跳转...';
                        setTimeout(function() {
                            window.location.href = url;
                        }, 1000);
                    }
                } else if (data.status === 'error') {
                    overlayText.textContent = '启动失败';
                    overlayError.textContent =
                        data.error || '未知错误';
                    setTimeout(function() {
                        overlay.classList.remove('show');
                    }, 3000);
                }
            } catch (e) {
                overlayText.textContent = '启动失败';
                overlayError.textContent = '网络错误: ' + e.message;
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

        // 帮助弹窗
        function showHelp() {
            document.getElementById('help-modal')
                .classList.add('show');
        }
        function hideHelp() {
            document.getElementById('help-modal')
                .classList.remove('show');
        }

        // 键盘事件
        document.addEventListener('keydown', function(e) {
            const key = e.key;

            // ESC 关闭弹窗
            if (key === 'Escape') {
                hideHelp();
                document.getElementById('overlay')
                    .classList.remove('show');
                return;
            }

            // 帮助弹窗打开时，仅响应 ? 和 0 关闭
            if (document.getElementById('help-modal')
                .classList.contains('show')) {
                if (key === '?' || key === '0') {
                    hideHelp();
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
                showHelp();
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

        // 初始化
        renderMenu();
        fetchStatus();
        // 检测 #drive hash 自动启动 DonkeyDrifter
        if (location.hash === '#drive') {
            launchDrive();
        }
    </script>
</body>
</html>"""
