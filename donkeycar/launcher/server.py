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
    """启动 donkey web + manage.py drive，返回结果字典。"""
    with _proc_lock:
        # 检查是否已在运行
        web_proc = _processes["web"]
        if web_proc is not None and web_proc.poll() is None:
            port = _processes["frontend_port"]
            return {
                "status": "already_running",
                "url": f"http://localhost:{port}/#/drive",
            }

        # 查找 mycar 项目
        project_path = _find_mycar_project()
        if project_path is None:
            return {
                "status": "error",
                "error": "未找到有效的 mycar 项目"
                         "（需包含 manage.py 和 myconfig.py）",
            }

        # 杀掉上一次的进程
        _kill_previous_drive_processes()

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

MENU_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Donkey Car 交互式管理终端</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            background: #0d1117;
            color: #e8edf2;
            font-family: 'Courier New', 'Consolas', 'Monaco', monospace;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 20px;
        }
        .container {
            width: 100%;
            max-width: 900px;
        }
        /* 橙色头部面板 */
        .header-panel {
            background: linear-gradient(135deg, #f78166 0%, #e5534b 100%);
            border-radius: 8px 8px 0 0;
            padding: 20px 30px;
            text-align: center;
            border: 1px solid #f78166;
            border-bottom: none;
        }
        .header-panel h1 {
            font-size: 22px;
            color: #fff;
            font-weight: bold;
            letter-spacing: 2px;
        }
        .header-panel .subtitle {
            font-size: 13px;
            color: rgba(255, 255, 255, 0.8);
            margin-top: 6px;
        }
        /* 当前目录显示 */
        .cwd-display {
            background: #161b22;
            border: 1px solid #30363d;
            border-top: none;
            padding: 10px 30px;
            font-size: 13px;
            color: #8b949e;
        }
        .cwd-display .label {
            color: #f78166;
        }
        .cwd-display .path {
            color: #56d4dd;
        }
        /* 菜单表格 */
        .menu-table {
            width: 100%;
            border-collapse: collapse;
            border: 1px solid #ff00ff;
            border-top: none;
            border-radius: 0 0 8px 8px;
            overflow: hidden;
        }
        .menu-table thead th {
            background: rgba(255, 0, 255, 0.12);
            color: #ff00ff;
            padding: 10px 16px;
            text-align: left;
            font-size: 14px;
            border-bottom: 1px solid rgba(255, 0, 255, 0.3);
            font-weight: bold;
        }
        .menu-table tbody tr {
            cursor: pointer;
            transition: background 0.15s;
            border-bottom: 1px solid #21262d;
        }
        .menu-table tbody tr:hover {
            background: rgba(56, 212, 221, 0.08);
        }
        .menu-table tbody tr.selected {
            background: rgba(56, 212, 221, 0.15);
            border-left: 3px solid #56d4dd;
        }
        .menu-table td {
            padding: 8px 16px;
            font-size: 13px;
        }
        .col-no   { color: #56d4dd; width: 50px;  text-align: center; }
        .col-cat  { color: #e3b341; width: 60px; }
        .col-name { color: #7ee787; width: 180px; }
        .col-name .favorite { color: #d2a8ff; }
        .col-desc { color: #8b949e; }
        /* 底部提示 */
        .footer-hint {
            margin-top: 16px;
            text-align: center;
            font-size: 13px;
            color: #6e7681;
        }
        .footer-hint .key {
            color: #f78166;
            background: rgba(247, 129, 102, 0.1);
            padding: 2px 8px;
            border-radius: 3px;
            margin: 0 2px;
        }
        /* 加载遮罩 */
        .overlay {
            display: none;
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0, 0, 0, 0.85);
            z-index: 1000;
            justify-content: center;
            align-items: center;
            flex-direction: column;
        }
        .overlay.active { display: flex; }
        .spinner {
            width: 50px;
            height: 50px;
            border: 4px solid #30363d;
            border-top-color: #f78166;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        .overlay-text {
            margin-top: 20px;
            font-size: 16px;
            color: #e8edf2;
        }
        .overlay-error {
            margin-top: 12px;
            font-size: 14px;
            color: #f85149;
            max-width: 500px;
            text-align: center;
        }
        /* 帮助模态框 */
        .modal {
            display: none;
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0, 0, 0, 0.7);
            z-index: 1001;
            justify-content: center;
            align-items: center;
        }
        .modal.active { display: flex; }
        .modal-content {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 8px;
            padding: 30px;
            max-width: 500px;
            width: 90%;
        }
        .modal-content h2 {
            color: #f78166;
            font-size: 18px;
            margin-bottom: 16px;
        }
        .modal-content p {
            color: #e8edf2;
            font-size: 13px;
            line-height: 1.8;
            margin-bottom: 8px;
        }
        .modal-content .close-btn {
            margin-top: 20px;
            padding: 8px 24px;
            background: #f78166;
            color: #fff;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
            font-family: inherit;
        }
        .modal-content .close-btn:hover { background: #e5534b; }
    </style>
</head>
<body>
    <div class="container">
        <!-- 橙色头部面板 -->
        <div class="header-panel">
            <h1>Donkey Car 交互式管理终端</h1>
            <div class="subtitle">DonkeyDrifter Web Launcher</div>
        </div>

        <!-- 当前目录 -->
        <div class="cwd-display">
            <span class="label">当前目录:</span>
            <span class="path" id="cwd-path">{{CWD}}</span>
        </div>

        <!-- 菜单表格 -->
        <table class="menu-table" id="menu-table">
            <thead>
                <tr>
                    <th class="col-no">No.</th>
                    <th class="col-cat">分类</th>
                    <th class="col-name">功能名称</th>
                    <th class="col-desc">描述</th>
                </tr>
            </thead>
            <tbody id="menu-body">
            </tbody>
        </table>

        <!-- 底部提示 -->
        <div class="footer-hint">
            提示: 输入<span class="key">编号</span>选择功能，
            输入 <span class="key">?</span> 显示帮助，
            输入 <span class="key">0</span> 退出
        </div>
    </div>

    <!-- 加载遮罩 -->
    <div class="overlay" id="overlay">
        <div class="spinner"></div>
        <div class="overlay-text" id="overlay-text">正在启动 DonkeyDrifter...</div>
        <div class="overlay-error" id="overlay-error"></div>
    </div>

    <!-- 帮助模态框 -->
    <div class="modal" id="help-modal">
        <div class="modal-content">
            <h2>帮助</h2>
            <p><span style="color:#56d4dd">数字键 1-10</span> — 选择对应菜单项</p>
            <p><span style="color:#56d4dd">?</span> — 显示此帮助信息</p>
            <p><span style="color:#56d4dd">0</span> — 返回上一页</p>
            <p><span style="color:#56d4dd">ESC</span> — 关闭弹窗</p>
            <p style="margin-top:12px;color:#8b949e;">
                带 <span style="color:#d2a8ff">[*]</span> 标记的为常用功能。
            </p>
            <p style="color:#8b949e;">
                目前仅支持通过浏览器启动「驾驶」功能 (选项 6)。
            </p>
            <button class="close-btn" onclick="hideHelp()">关闭</button>
        </div>
    </div>

    <script>
        // 菜单项数据（与 tui.py 保持一致）
        const menuItems = [
            {no: 1,  category: "管理", name: "createcar",    desc: "创建新的 DonkeyCar 项目",                    favorite: true},
            {no: 2,  category: "管理", name: "open",         desc: "打开已有 DonkeyCar 项目",                    favorite: false},
            {no: 3,  category: "数据", name: "clear_data",   desc: "清空当前项目 data 目录",                     favorite: true},
            {no: 4,  category: "数据", name: "backup_data",  desc: "备份当前项目 data 目录",                     favorite: false},
            {no: 5,  category: "数据", name: "restore_data", desc: "从备份恢复 data 目录",                       favorite: false},
            {no: 6,  category: "驾驶", name: "drive",        desc: "打开 Web Console 驾驶控制台",                 favorite: true},
            {no: 7,  category: "筛选", name: "web",          desc: "启动 Web UI（前后端）",                      favorite: true},
            {no: 8,  category: "筛选", name: "donkey_ui",    desc: "启动数据筛选工具（Windows下需要WSL来运行）", favorite: false},
            {no: 9,  category: "训练", name: "train_local",  desc: "本地训练",                                    favorite: false},
            {no: 10, category: "训练", name: "train_online", desc: "云端训练（train_online.conf）",              favorite: true},
        ];

        let selectedNo = null;
        let pendingDigit1 = null;

        // 渲染菜单表格
        function renderMenu() {
            const tbody = document.getElementById('menu-body');
            tbody.innerHTML = '';
            menuItems.forEach(item => {
                const tr = document.createElement('tr');
                tr.dataset.no = item.no;
                tr.onclick = () => selectItem(item.no);
                const favMark = item.favorite
                    ? ' <span class="favorite">[*]</span>' : '';
                tr.innerHTML =
                    '<td class="col-no">' + item.no + '</td>' +
                    '<td class="col-cat">' + item.category + '</td>' +
                    '<td class="col-name">' + item.name + favMark + '</td>' +
                    '<td class="col-desc">' + item.desc + '</td>';
                tbody.appendChild(tr);
            });
        }

        // 高亮选中行
        function highlightRow(no) {
            document.querySelectorAll('#menu-body tr').forEach(tr => {
                tr.classList.toggle(
                    'selected', parseInt(tr.dataset.no) === no
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
            overlay.classList.add('active');
            overlayText.textContent = '正在启动 DonkeyDrifter...';
            overlayError.textContent = '';

            try {
                const resp = await fetch('/api/launch/drive', {
                    method: 'POST'
                });
                const data = await resp.json();

                if (data.status === 'launched' ||
                    data.status === 'already_running') {
                    // 替换 localhost 为实际主机名
                    // （用户可能从其他设备访问）
                    const url = data.url.replace(
                        'localhost', window.location.hostname
                    );
                    overlayText.textContent =
                        '启动成功！正在跳转到 Web Console...';
                    setTimeout(function() {
                        window.location.href = url;
                    }, 1500);
                } else if (data.status === 'error') {
                    overlayText.textContent = '启动失败';
                    overlayError.textContent =
                        data.error || '未知错误';
                    setTimeout(function() {
                        overlay.classList.remove('active');
                    }, 3000);
                }
            } catch (e) {
                overlayText.textContent = '启动失败';
                overlayError.textContent = '网络错误: ' + e.message;
                setTimeout(function() {
                    overlay.classList.remove('active');
                }, 3000);
            }
        }

        // 显示错误提示
        function showError(msg) {
            const overlay = document.getElementById('overlay');
            const overlayText = document.getElementById('overlay-text');
            const overlayError = document.getElementById('overlay-error');
            overlay.classList.add('active');
            overlayText.textContent = '';
            overlayError.textContent = msg;
            setTimeout(function() {
                overlay.classList.remove('active');
            }, 2500);
        }

        // 帮助模态框
        function showHelp() {
            document.getElementById('help-modal')
                .classList.add('active');
        }
        function hideHelp() {
            document.getElementById('help-modal')
                .classList.remove('active');
        }

        // 键盘事件
        document.addEventListener('keydown', function(e) {
            const key = e.key;

            // ESC 关闭弹窗
            if (key === 'Escape') {
                hideHelp();
                document.getElementById('overlay')
                    .classList.remove('active');
                return;
            }

            // 帮助弹窗打开时，仅响应 ? 和 0 关闭
            if (document.getElementById('help-modal')
                .classList.contains('active')) {
                if (key === '?' || key === '0') {
                    hideHelp();
                }
                return;
            }

            // 遮罩打开时不处理菜单导航
            if (document.getElementById('overlay')
                .classList.contains('active')) {
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
                // 非 0 则继续正常处理
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
                // 返回上一页
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
    </script>
</body>
</html>"""
