# TUI Web UI 路径修复设计

## 背景

在车辆项目目录（例如 `/home/user/projects/mycar`）中打开 Donkey Car 交互式管理终端并选择 `web` 功能时，TUI 当前预览并执行裸命令：

```bash
donkey web
```

`donkey web` 会从当前工作目录向上查找 `web_ui`。车辆项目目录通常不包含仓库级 `web_ui`，因此启动失败并提示需要手动指定 `--path`。

## 目标

TUI 的 `web` 菜单应默认启动 DonkeyDrifter 仓库内置 Web UI。用户在任意有效车辆项目目录中选择 `web` 后，命令预览应包含显式路径：

```bash
donkey web --path <DonkeyDrifter仓库或源码包中的web_ui目录>
```

## 非目标

- 不改变 `donkey web` 子命令本身的默认路径解析策略。
- 不把 `web_ui` 复制到每个车辆项目目录。
- 不新增交互式路径输入；本次修复保持菜单操作简单。

## 方案

在 `donkeycar/management/tui.py` 中为 TUI 增加仓库内置 Web UI 路径解析：

1. 从 `tui.py` 所在位置推断源码根目录。
2. 检查 `<root>/web_ui/frontend` 与 `<root>/web_ui/backend` 是否存在。
3. 若检查通过，`WebUICommand.get_command_line()` 返回：

   ```python
   ["donkey", "web", "--path", str(web_ui_path)]
   ```

4. 若检查失败，保留裸 `donkey web` 作为回退，让现有 `donkey web` 错误提示继续说明如何手动传入 `--path`。

## 数据流

1. 用户在 TUI 主菜单选择 `web`。
2. `WebUICommand.get_command_line({})` 解析内置 `web_ui` 路径。
3. TUI 展示完整命令预览。
4. 用户确认后，TUI 使用现有 `subprocess.Popen(cmd_list, ...)` 执行该命令。
5. `donkey web --path ...` 使用显式路径启动前后端。

## 错误处理

- 如果源码布局完整，TUI 不依赖当前工作目录查找 `web_ui`。
- 如果无法定位内置 Web UI，TUI 不提前抛出新异常，而是回退到原命令，复用 `donkey web` 的现有失败提示。
- 路径检查以 `frontend` 和 `backend` 两个子目录为准，避免指向错误目录。

## 测试策略

新增或扩展 TUI 单元测试，覆盖：

1. `WebUICommand().get_command_line({})` 不再返回裸 `['donkey', 'web']`。
2. 命令包含 `--path`。
3. `--path` 后的目录存在，且包含 `frontend` 与 `backend` 子目录。

建议运行：

```bash
pytest tests/test_tui_web_command.py -q
```

若测试文件放在其他位置，则运行对应新增测试文件。

## 验收标准

- 在 `/home/user/projects/mycar` 中打开 TUI 并选择 `web`，命令预览显示 `donkey web --path .../web_ui`。
- 确认执行后，不再因为当前车辆目录缺少 `web_ui` 而立即失败。
- 新增测试通过。
