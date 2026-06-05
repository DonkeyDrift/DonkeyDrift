# Car Connector 实车/远端手工验证指南

## 目标

验证 Car Connector 在真实车端或远端 Donkeycar 环境中的完整链路：SSH 连接、远端目录读取、rsync 同步、远程启动/停止驾驶、DriveApiBridge 回连、前端任务日志与状态提示。

## 前置条件

### 本机

- 已安装并可运行 Web UI 后端与前端。
- 已安装 OpenSSH 客户端，命令行可执行 `ssh`。
- 已安装 `rsync`。
- 本机与车端在同一网络，或本机可通过 SSH 访问车端。
- 浏览器可以访问 Web UI 前端。

### 车端

- 车端已安装 OpenSSH 服务，并允许本机登录。
- 车端已安装 `rsync`。
- 车端 Donkeycar 车目录存在，例如 `~/mycar`。
- 车目录中可以执行：

```bash
python manage.py drive
```

- 如果要验证 Pilot 驾驶，车端 `~/mycar/models` 下至少有一个模型文件。
- 如果要验证 Tub 拉取，车端车目录下至少有一个 Tub 数据目录。

## 启动 Web UI

在仓库根目录分别启动后端和前端。

后端：

```bash
cd web_ui/backend
python main.py
```

前端：

```bash
cd web_ui/frontend
npm run dev
```

默认情况下：

- 后端监听 `http://0.0.0.0:8000`
- 前端监听 Vite 输出的本地地址，通常是 `http://localhost:5188`

## 验证步骤

### 1. 保存连接配置

打开前端页面，进入 `Car Connector`。

填写连接配置：

- 主机地址：车端 IP 或主机名，例如 `192.168.1.20` 或 `donkeycar.local`
- 用户名：例如 `pi`
- SSH 端口：通常为 `22`
- 车端目录：例如 `~/mycar`
- SSH 密钥路径：如果使用密钥登录，填写本机密钥路径；如果使用默认 SSH 配置，可留空

点击 `保存配置`。

预期结果：

- 按钮短暂显示保存中。
- 页面不出现错误。
- 刷新页面后配置仍能加载。

### 2. 检查 SSH 连接

点击 `检查连接`。

预期结果：

- 成功时显示类似 `已连接到 <host>`。
- 失败时显示具体 SSH 错误，例如认证失败、连接超时、主机不可达。

如果失败，先在本机终端手动验证：

```bash
ssh -p 22 pi@192.168.1.20 date
```

如果使用密钥：

```bash
ssh -i ~/.ssh/id_rsa -p 22 pi@192.168.1.20 date
```

### 3. 验证远端 Tub 和模型列表

连接检查成功后，页面应自动加载远端列表。

预期结果：

- `拉取 Tub` 下拉框能看到车端车目录下的 Tub 或数据目录。
- `选择 Pilot` 下拉框能看到车端 `models` 目录下的模型文件。

如果列表为空：

- 确认车端 `~/mycar` 下确实有 Tub 目录。
- 确认车端 `~/mycar/models` 下确实有模型文件。
- 确认车端目录配置没有填错。

### 4. 验证 rsync 预检测

#### 4.1 正常路径

确保本机和车端都安装了 `rsync`。

本机检查：

```bash
rsync --version
```

车端检查：

```bash
ssh pi@192.168.1.20 'command -v rsync && rsync --version | head -n 1'
```

点击页面中的 `拉取 Tub` 或 `推送选中格式`。

预期结果：

- 任务进入运行状态。
- 日志中出现同步进度或 rsync 输出。
- 不出现“本机缺少 rsync”或“车端缺少 rsync”。

#### 4.2 本机缺少 rsync 场景

仅在测试环境中验证，不建议修改正常开发环境。

可使用一个不包含 `rsync` 的 PATH 启动后端，或临时在无 rsync 环境中运行后端。

预期结果：

- 拉取或推送任务失败。
- 日志或错误信息包含：`本机缺少 rsync`。
- 后端不会继续执行同步。

#### 4.3 车端缺少 rsync 场景

仅在可恢复的测试车端验证，不建议卸载生产车端依赖。

如果车端没有 rsync，点击拉取或推送。

预期结果：

- 任务失败。
- 日志或错误信息包含：`车端缺少 rsync`。
- 页面给出安装提示。

### 5. 验证 Tub 拉取和自动刷新

在 `拉取 Tub` 区域选择一个远端 Tub。

#### 5.1 覆盖/合并到 `./data`

取消勾选 `创建新目录（不覆盖现有数据）`，点击 `拉取 <Tub>`。

预期结果：

- 任务日志显示 rsync 同步过程。
- 任务完成后进度为 100%。
- 页面状态显示类似 `Tub 已拉取并刷新: ...`。
- Tub Manager 或数据浏览区域的当前 Tub 更新为本地 `./data` 对应路径。

#### 5.2 拉取到新目录

勾选 `创建新目录（不覆盖现有数据）`，点击 `拉取 <Tub>`。

预期结果：

- 远端 Tub 被拉取到本地 `./data/<远端 Tub 名称>`。
- 任务完成后自动加载该本地 Tub。
- 页面状态显示拉取并刷新成功。

如果 rsync 成功但 Tub 刷新失败：

- 任务本身仍应显示完成。
- 页面状态应显示 `Tub 已拉取，但本地刷新失败: ...`。
- 检查本地目录是否为有效 Tub v2 数据格式。

### 6. 验证推送 Pilots

进入 `推送 Pilots` 区域。

#### 6.1 推送选中格式

选择一个或多个格式，例如 `TFLite`、`H5`，点击 `推送选中格式`。

预期结果：

- 任务日志显示 rsync 输出。
- 车端 `~/mycar/models` 中出现对应格式的模型文件。
- 未选中的模型格式不会被推送。

#### 6.2 一键全选

点击 `一键全选`。

预期结果：

- `TFLite`、`H5`、`SavedModel`、`TensorRT` 全部处于选中状态。
- 点击 `推送选中格式` 后会同步所有选中格式。

#### 6.3 同步全部

点击 `同步全部`。

预期结果：

- 前端显式发送空格式数组。
- 后端按“同步全部”语义同步 `./models` 中所有模型内容。
- 车端 `~/mycar/models` 与本机 `./models` 内容保持一致，受 rsync 行为影响。

### 7. 验证远程启动驾驶

进入 `远程驾驶` 区域。

确认 `DriveApiBridge 回连地址`：

- 如果车端和 Web UI 后端在同一台机器，可使用自动生成地址。
- 如果车端在另一台机器，必须把 `localhost` 或 `127.0.0.1` 改成本机在局域网中的 IP。
- 地址格式必须是 WebSocket URL，例如：

```text
ws://192.168.1.10:8000/api/drive/ws
```

#### 7.1 手动驾驶启动

保持 `选择 Pilot` 为 `无 Pilot（手动驾驶）`，点击 `启动驾驶`。

预期结果：

- 任务完成。
- 页面显示远程驾驶 PID。
- 车端车目录下生成 `.donkeycar_drive.pid`。
- 车端车目录下生成或更新 `.donkeycar_drive.log`。

在车端检查：

```bash
cd ~/mycar
cat .donkeycar_drive.pid
ps -p "$(cat .donkeycar_drive.pid)" -o pid,args=
```

预期进程命令行包含 `manage.py drive`。

#### 7.2 Pilot 驾驶启动

选择一个 Pilot 和匹配的模型类型，点击 `启动驾驶`。

预期结果：

- 任务完成。
- 页面显示远程驾驶 PID。
- 车端进程命令行包含 `manage.py drive`、`--type` 和 `--model`。
- `.donkeycar_drive.log` 中没有模型加载错误。

### 8. 验证 Drive 控制通道在线提示

远程驾驶启动后，等待数秒。

预期结果：

- `远程驾驶` 卡片中显示绿色提示：`车端已在线，可直接打开驾驶控制台`。
- 点击 `打开驾驶控制台` 后进入 Drive 页面。
- Drive 页面能显示车端在线状态。
- 控制输入能通过 `/api/drive/ws` 下发到车端。

如果一直显示 `车端尚未连接 Drive 控制通道` 或 `Drive 状态通道连接中...`：

- 检查 `DriveApiBridge 回连地址` 是否使用了车端可访问的本机局域网 IP。
- 检查后端端口 `8000` 是否被防火墙阻止。
- 检查车端 `.donkeycar_drive.log` 是否有 WebSocket 连接错误。

### 9. 验证安全停车

点击 `停止驾驶`。

预期结果：

- 停车任务完成。
- 页面远程驾驶 PID 变为 `未运行`，或刷新后显示未运行。
- 车端 `.donkeycar_drive.pid` 被删除。
- 车端 `manage.py drive` 进程退出。

车端检查：

```bash
cd ~/mycar
test ! -f .donkeycar_drive.pid && echo 'pidfile 已删除'
ps aux | grep 'manage.py drive' | grep -v grep
```

### 10. 验证拒绝误杀非驾驶进程

此步骤用于验证 PID 安全校验，建议只在测试车端执行。

#### 10.1 pidfile 不匹配

先启动远程驾驶，记录页面显示的 PID。

在车端修改 pidfile 为另一个 PID：

```bash
cd ~/mycar
echo 1 > .donkeycar_drive.pid
```

回到页面点击 `停止驾驶`。

预期结果：

- 停车任务失败。
- 日志包含 `PID 与 .donkeycar_drive.pid 不匹配，已拒绝停止`。
- 原驾驶进程仍然存在。
- 页面仍保留原 PID，不应清空。

恢复 pidfile：

```bash
cd ~/mycar
echo '<原驾驶 PID>' > .donkeycar_drive.pid
```

然后再次点击 `停止驾驶`，应能正常停止。

#### 10.2 非 Donkeycar drive 进程

不建议从页面直接输入任意 PID；如果需要验证，可通过后端接口或测试环境构造一个非 `manage.py drive` PID。

预期结果：

- 停车任务失败。
- 日志包含 `PID 不是 Donkeycar drive 进程，已拒绝停止`。
- 非驾驶进程不会被杀掉。

#### 10.3 工作目录不匹配

如果存在另一个目录中的 `manage.py drive` 进程，尝试用当前车目录配置停止该 PID。

预期结果：

- 停车任务失败。
- 日志包含 `PID 工作目录不匹配，已拒绝停止`。
- 其他目录中的进程不会被杀掉。

## 验收清单

- [ ] 可以保存 Connector 配置。
- [ ] 可以通过 SSH 连接检查。
- [ ] 可以加载远端 Tub 列表。
- [ ] 可以加载远端模型列表。
- [ ] 本机缺少 rsync 时错误明确。
- [ ] 车端缺少 rsync 时错误明确。
- [ ] 可以拉取 Tub。
- [ ] Tub 拉取完成后自动刷新本地 Tub。
- [ ] 可以推送选中模型格式。
- [ ] `一键全选` 能选中全部格式。
- [ ] `同步全部` 能同步全部模型内容。
- [ ] 可以远程启动手动驾驶。
- [ ] 可以远程启动 Pilot 驾驶。
- [ ] 启动驾驶后页面显示 PID。
- [ ] 启动驾驶后车端生成 `.donkeycar_drive.pid`。
- [ ] Drive 控制通道在线后页面显示 `车端已在线，可直接打开驾驶控制台`。
- [ ] 可以打开 Drive 控制台并控制车端。
- [ ] 停车会校验 pidfile、命令行和工作目录。
- [ ] 正常停车后进程退出且 pidfile 删除。
- [ ] pidfile 不匹配时拒绝停车且不清空 PID。
- [ ] 非 Donkeycar drive 进程不会被误杀。

## 常见问题排查

### SSH 连接失败

- 确认车端 IP 正确。
- 确认 SSH 端口正确。
- 确认用户名正确。
- 手动执行 `ssh -p <端口> <用户>@<主机> date`。
- 如果首次连接，需要先在终端接受 host key。

### 远端列表加载失败

- 确认 `车端目录` 指向 Donkeycar 车目录。
- 确认用户有权限读取该目录。
- 手动执行：

```bash
ssh pi@192.168.1.20 'ls -1 ~/mycar'
ssh pi@192.168.1.20 'ls -1 ~/mycar/models'
```

### rsync 同步失败

- 确认本机和车端均已安装 `rsync`。
- 确认 SSH 登录不需要交互输入密码，或已完成必要认证。
- 确认本机 `./data` 和 `./models` 路径存在且有权限。

### DriveApiBridge 无法在线

- 不要把回连地址留成车端无法访问的 `localhost`。
- 使用本机局域网 IP，例如 `ws://192.168.1.10:8000/api/drive/ws`。
- 检查本机防火墙是否允许车端访问后端端口。
- 查看车端 `.donkeycar_drive.log` 中的 WebSocket 错误。

### 停车失败

- 查看任务日志中的拒绝原因。
- 在车端检查 `.donkeycar_drive.pid` 是否存在且内容正确。
- 在车端检查 PID 是否仍存在：

```bash
ps -p <PID> -o pid,args=
readlink /proc/<PID>/cwd
```
