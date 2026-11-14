# Web Console 带令牌连接操作说明

适用场景：本机以外的设备（手机/平板/另一台电脑）或本机浏览器用局域网 IP 访问
Web Console（驾驶页 `/drive`、连接器等）。本机回环访问（`127.0.0.1`/`localhost`）
**不需要**令牌，可直接阅读[驾驶控制台用户文档](web-drive-console-user-guide.md)。

> 机制出处：`web_ui/backend/auth.py`（P0 安全补强，2026-10-12 起生效）。
> 本文是操作手册，策略细节以该文件模块注释为准。

## 一、什么时候需要令牌

| 访问来源 | 是否需要令牌 | 说明 |
| --- | --- | --- |
| `http://127.0.0.1:8000`、`http://localhost:8000` | 否 | 回环 TCP + 本机 Host + 干净 Origin 直接放行 |
| `http://<局域网IP>:8000`（本机浏览器也算） | **是** | 本机用 LAN IP 访问，TCP 来源是 LAN IP 而非回环，一律按远程处理 |
| 局域网其他设备、SSH 远程终端用户的浏览器 | **是** | 同上 |
| 车端 `DriveApiBridge` 的 WS 回连 | 是（自动） | 车端自动从同一令牌文件取令牌拼入 WS URL，无需人工干预 |

典型症状对照：

- **拒绝访问 / ERR_CONNECTION_REFUSED**：后端绑了 `127.0.0.1`（默认），不是令牌问题——见第二节。
- **401 页面 / `{"error":"unauthorized"}`**：地址通了但没带令牌或 Cookie 已失效——见第三节。

## 二、前提：后端绑定地址

`donkey web` 默认只绑 `127.0.0.1`。要允许局域网访问，必须显式对外监听：

```bash
donkey web --path web_ui --backend-port 8000 --backend-host 0.0.0.0 --route /drive
# 或等价地：DRIVE_WEB_HOST=0.0.0.0 donkey web ...
```

检查当前后端绑的是什么：

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
#   TCP 127.0.0.1:8000 (LISTEN)  → 仅本机，LAN 地址会被拒
#   TCP *:8000 (LISTEN)          → 对外监听，LAN 可访问
```

说明：launcher 实车链路（`launcher/server.py`）自己起后端时**自动带
`--backend-host 0.0.0.0`**；TUI「配置 Drive」检测到已运行实例时是复用其绑定，
不会改绑。

## 三、令牌在哪、怎么用

### 令牌来源（优先级从高到低）

1. 环境变量 `DRIVE_API_TOKEN`
2. 文件 `~/.donkeycar/drive_api.token`（权限 0600；不存在时后端首次启动自动生成并落盘）

查看当前令牌：

```bash
cat ~/.donkeycar/drive_api.token
```

### 浏览器接入（推荐）

- **TUI「配置 Drive」**：2026-10-22（commit `fae83c59`）起自动用带令牌的 URL
  打开浏览器，无需手动操作。
- **手动 / 远程设备**：在浏览器打开

  ```
  http://<主机局域网IP>:8000/?token=<令牌>/#/drive
  ```

  注意 `?token=` 必须在 `#` **之前**（查询串才会发给服务器）。后端验证后会
  种下 Cookie（`dd_drive_token`，HttpOnly）并 302 跳到干净地址；此后该浏览器
  直接用 `http://<主机局域网IP>:8000/#/drive` 即可，直到令牌轮换。

### API / 脚本接入

四种等价凭据，任选其一：

```bash
TOKEN=$(cat ~/.donkeycar/drive_api.token)

# 1. 查询串
curl "http://192.168.3.44:8000/api/drive/stats?token=$TOKEN"
# 2. Bearer 头
curl -H "Authorization: Bearer $TOKEN" http://192.168.3.44:8000/api/drive/stats
# 3. 自定义头
curl -H "X-Donkey-Token: $TOKEN" http://192.168.3.44:8000/api/drive/stats
# 4. Cookie
curl --cookie "dd_drive_token=$TOKEN" http://192.168.3.44:8000/api/drive/stats
```

显式令牌（`?token=`/Bearer/自定义头）不受 Origin 限制，适合车端 WS、curl、
跨设备页面；仅凭 Cookie 通行额外要求本机 Host + 同源（防 CSRF/DNS rebinding）。

### 逃生舱：整体关闭鉴权

```bash
DRIVE_API_AUTH=off donkey web --backend-host 0.0.0.0 ...
```

仅在可信网络调试时使用；公网或不可信局域网**不要**关。

## 四、轮换 / 吊销令牌

```bash
rm ~/.donkeycar/drive_api.token
# 重启后端（会生成新令牌并落盘）
```

旧令牌与所有已种 Cookie 立即失效。车端无需改配置——`DriveApiBridge` 与后端
读同一个文件，重启车端进程即自动使用新令牌。

## 五、故障排查速查

| 症状 | 最可能原因 | 处理 |
| --- | --- | --- |
| LAN 地址拒绝访问 | 后端绑了 127.0.0.1 | 加 `--backend-host 0.0.0.0` 重启后端 |
| 401 unauthorized 页面 | URL 没带令牌，或令牌轮换后 Cookie 失效 | 重新用 `?token=` 完整地址访问一次 |
| 页面能开但「车端离线」 | 车端进程没起来，或 `drive_instance.json` 陈旧登记挡住启动器 | 确认旧进程不在后删 `~/.donkeycar/drive_instance.json` 再启动 |
| 启动器每次都不复用后端、重复新起 | `webui.json` 陈旧登记 | 删 `~/.donkeycar/webui.json` |
| 带令牌也 401 | 令牌不一致（后端/车端读到不同文件，或 env 覆盖） | 核对 `DRIVE_API_TOKEN` 环境变量与文件内容 |

## 六、安全注意

- `0.0.0.0` + 令牌 = **同网段内持令牌者可完全控制车辆**（含驾驶指令）。
  带令牌的完整 URL 等同钥匙，不要发到群聊、issue、截图等公开渠道。
- 公共/不可信网络改用 SSH 隧道代替对外监听：

  ```bash
  ssh -L 8000:127.0.0.1:8000 <用户名>@<主机>
  # 本地浏览器访问 http://127.0.0.1:8000/#/drive ——回环免令牌
  ```

- 怀疑令牌泄露：按第四节轮换即可，成本为零。
