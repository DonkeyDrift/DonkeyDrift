#!/usr/bin/env python3
"""
Donkey Car 交互式管理终端 (DonkeyUI)
基于 rich 和 prompt_toolkit 构建
"""
import sys
import os
import json
import subprocess
import time
import threading
import queue
import shutil
import getpass
from datetime import datetime
from typing import List, Dict, Any, Optional, Callable, Tuple
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.prompt import Prompt, Confirm, IntPrompt
from rich.align import Align
from rich import box
from rich.markdown import Markdown
from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn

# 初始化 Console
console = Console()

# -----------------------------------------------------------------------------
# 历史记录管理
# -----------------------------------------------------------------------------
class HistoryManager:
    def __init__(self, history_file: str = ".donkey_history"):
        self.history_file = Path(history_file)
        self.history = self._load()

    def _load(self) -> Dict[str, Any]:
        if self.history_file.exists():
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save(self):
        try:
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(self.history, f, indent=2, ensure_ascii=False)
        except Exception as e:
            console.print(f"[red]保存历史记录失败: {e}[/red]")

    def get_last_params(self, command_name: str) -> Dict[str, Any]:
        return self.history.get("commands", {}).get(command_name, {})

    def update_last_params(self, command_name: str, params: Dict[str, Any]):
        if "commands" not in self.history:
            self.history["commands"] = {}
        self.history["commands"][command_name] = params
        self.save()

    def add_command_log(self, command_str: str):
        if "log" not in self.history:
            self.history["log"] = []
        self.history["log"].append({
            "timestamp": datetime.now().isoformat(),
            "command": command_str
        })
        # 保持最近 50 条
        if len(self.history["log"]) > 50:
            self.history["log"] = self.history["log"][-50:]
        self.save()

    def add_action_log(self, action: str, result: str, detail: Optional[Dict[str, Any]] = None):
        if "actions" not in self.history:
            self.history["actions"] = []
        entry = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "user": getpass.getuser(),
            "result": result
        }
        if detail:
            entry["detail"] = detail
        self.history["actions"].append(entry)
        if len(self.history["actions"]) > 50:
            self.history["actions"] = self.history["actions"][-50:]
        self.save()

# -----------------------------------------------------------------------------
# 辅助函数
# -----------------------------------------------------------------------------
def is_valid_mycar_folder():
    """检查当前目录是否为有效的 mycar 项目"""
    return os.path.exists("manage.py") and os.path.exists("myconfig.py")

def _human_readable_size(size_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    size = float(size_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.2f} {unit}"
        size /= 1024

def _scan_directory(path: Path) -> Tuple[int, int]:
    file_count = 0
    total_size = 0
    if not path.exists():
        return file_count, total_size
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total_size += (Path(root) / name).stat().st_size
            except OSError:
                pass
            file_count += 1
    return file_count, total_size

def _move_items_to_trash(data_dir: Path, trash_dir: Path) -> Tuple[List[Path], List[str]]:
    moved = []
    errors = []
    trash_dir.mkdir(parents=True, exist_ok=True)
    for item in data_dir.iterdir():
        target = trash_dir / item.name
        try:
            shutil.move(str(item), str(target))
            moved.append(target)
        except Exception as e:
            errors.append(f"{item}: {e}")
    return moved, errors

def _restore_from_trash(trash_dir: Path, data_dir: Path) -> List[str]:
    errors = []
    data_dir.mkdir(parents=True, exist_ok=True)
    for item in trash_dir.iterdir():
        target = data_dir / item.name
        try:
            shutil.move(str(item), str(target))
        except Exception as e:
            errors.append(f"{item}: {e}")
    return errors

def _delete_directory_contents(trash_dir: Path, progress_callback: Callable[[int], None]) -> List[str]:
    errors = []
    for root, dirs, files in os.walk(trash_dir, topdown=False):
        for name in files:
            path = Path(root) / name
            try:
                path.unlink()
                progress_callback(1)
            except Exception as e:
                errors.append(f"{path}: {e}")
        for name in dirs:
            path = Path(root) / name
            try:
                path.rmdir()
            except Exception as e:
                errors.append(f"{path}: {e}")
    return errors

# -----------------------------------------------------------------------------
# 命令定义基类
# -----------------------------------------------------------------------------
class CommandOption:
    def __init__(self, name: str, prompt_text: str, default: Any = None, required: bool = True, 
                 validator: Callable[[str], bool] = None, help_text: str = ""):
        self.name = name
        self.prompt_text = prompt_text
        self.default = default
        self.required = required
        self.validator = validator
        self.help_text = help_text

class DonkeyCommand:
    def __init__(self, name: str, description: str, category: str, is_favorite: bool = False, requires_mycar_folder: bool = True):
        self.name = name
        self.description = description
        self.category = category
        self.is_favorite = is_favorite
        self.requires_mycar_folder = requires_mycar_folder
        self.options: List[CommandOption] = []
        self.history_mgr = HistoryManager()

    def get_command_line(self, params: Dict[str, Any]) -> List[str]:
        raise NotImplementedError

    def on_success(self, params: Dict[str, Any]):
        """命令执行成功后的回调"""
        pass

    def execute(self):
        console.clear()
        console.print(Panel(f"[bold blue]{self.description}[/bold blue]", title=f"配置 {self.name}"))
        
        # 检查是否需要有效的 mycar 目录
        if self.requires_mycar_folder and not is_valid_mycar_folder():
            console.print(Panel(
                "[bold red]错误：当前目录不是有效的 mycar 项目文件夹！[/bold red]\n\n"
                "缺少关键文件：manage.py 或 myconfig.py\n"
                "请先执行 [bold yellow]createcar[/bold yellow] 命令创建新的车辆项目。",
                title="环境检查失败",
                border_style="red"
            ))
            Prompt.ask("按回车键返回菜单...")
            return

        last_params = self.history_mgr.get_last_params(self.name)
        current_params = {}

        # 1. 收集参数
        for opt in self.options:
            default_val = last_params.get(opt.name, opt.default)
            prompt_text = f"{opt.prompt_text}"
            if opt.help_text:
                console.print(f"[dim]{opt.help_text}[/dim]")
            
            while True:
                val = Prompt.ask(prompt_text, default=str(default_val) if default_val is not None else None)
                if not val and opt.required and default_val is None:
                    console.print("[red]此项为必填项[/red]")
                    continue
                
                if opt.validator and val:
                    if not opt.validator(val):
                        console.print(f"[red]输入无效，请重新输入[/red]")
                        continue
                
                current_params[opt.name] = val
                break

        # 2. 生成预览
        cmd_list = self.get_command_line(current_params)
        cmd_str = " ".join(cmd_list)
        
        console.print("\n[bold yellow]命令预览:[/bold yellow]")
        console.print(Panel(f"[green]{cmd_str}[/green]", title="Shell Command"))

        # 3. 确认执行
        console.print("([green]y[/green]:执行 [red]n[/red]:取消 [blue]c[/blue]:复制命令)")
        action = Prompt.ask(
            "请选择操作", 
            choices=["y", "n", "c", "copy"], 
            default="y",
            show_choices=False
        )

        if action == "copy":
            import pyperclip
            try:
                pyperclip.copy(cmd_str)
                console.print("[green]✓ 命令已复制到剪贴板[/green]")
            except ImportError:
                console.print("[red]✗ 未安装 pyperclip，无法复制。请手动复制上方命令。[/red]")
            Prompt.ask("按回车键返回...")
            return

        if action != "y":
            console.print("[yellow]操作已取消[/yellow]")
            time.sleep(1)
            return

        # 4. 执行并记录
        self.history_mgr.update_last_params(self.name, current_params)
        self.history_mgr.add_command_log(cmd_str)
        
        console.print(f"\n[bold cyan]>> [{datetime.now().strftime('%H:%M:%S')}] 开始执行...[/bold cyan]")
        try:
            # 使用 subprocess.run 实时显示输出有点麻烦，这里直接让子进程接管 stdio
            # 或者使用 Popen 读取 pipe
            process = subprocess.Popen(
                cmd_list, 
                stdout=sys.stdout, 
                stderr=sys.stderr,
                text=True
            )
            process.wait()
            
            if process.returncode == 0:
                console.print(f"\n[bold green]✓ 执行成功 (Exit Code: 0)[/bold green]")
                self.on_success(current_params)
            else:
                console.print(f"\n[bold red]✗ 执行失败 (Exit Code: {process.returncode})[/bold red]")
                console.print(f"[dim]请检查上方错误日志[/dim]")

        except Exception as e:
            console.print(f"\n[bold red]✗ 发生异常: {e}[/bold red]")
        
        Prompt.ask("\n按回车键返回菜单...")

# -----------------------------------------------------------------------------
# 具体命令实现
# -----------------------------------------------------------------------------

class CreateCarCommand(DonkeyCommand):
    def __init__(self):
        super().__init__("createcar", "创建新的 DonkeyCar 项目", "管理", is_favorite=True, requires_mycar_folder=False)
        self.options = [
            CommandOption("folder", "项目名称", default="mycar", help_text="将在 ~/projects/ 下创建此目录"),
            CommandOption("template", "模板名称", default=None, required=False, help_text="可选模板: basic, square 等 (留空使用默认)"),
            CommandOption("overwrite", "是否覆盖", default="n", validator=lambda x: x.lower() in ['y', 'n'], help_text="如果目录存在是否覆盖 (y/n)")
        ]

    def on_success(self, params):
        base_dir = os.path.expanduser("~/projects")
        full_path = os.path.join(base_dir, params["folder"])
        
        if os.path.exists(full_path):
            try:
                os.chdir(full_path)
                console.print(Panel(f"[bold green]✓ 已切换工作目录至: {full_path}[/bold green]\n"
                                    f"[dim]现在您可以直接运行 train 或 drive 命令了[/dim]",
                                    title="环境自动配置"))
            except Exception as e:
                console.print(f"[red]切换目录失败: {e}[/red]")
        else:
            console.print(f"[yellow]警告: 目录 {full_path} 不存在，无法切换[/yellow]")

    def get_command_line(self, params):
        base_dir = os.path.expanduser("~/projects")
        full_path = os.path.join(base_dir, params["folder"])
        cmd = ["donkey", "createcar", "--path", full_path]
        if params.get("template"):
            cmd.extend(["--template", params["template"]])
        if params.get("overwrite", "").lower() == 'y':
            cmd.append("--overwrite")
        return cmd

class OpenProjectCommand(DonkeyCommand):
    def __init__(self):
        super().__init__("open", "打开已有 DonkeyCar 项目", "管理", is_favorite=True, requires_mycar_folder=False)
        self.options = [] # No options needed, we'll ask interactively

    def execute(self):
        console.clear()
        console.print(Panel(f"[bold blue]{self.description}[/bold blue]", title=f"配置 {self.name}"))
        
        base_dir = Path(os.path.expanduser("~/projects"))
        if not base_dir.exists():
             console.print(f"[red]项目根目录 {base_dir} 不存在！[/red]")
             Prompt.ask("按回车键返回...")
             return

        console.print(f"[dim]正在扫描 {base_dir} 下的项目...[/dim]")
        
        valid_projects = []
        try:
            for item in base_dir.iterdir():
                if item.is_dir():
                    if (item / "manage.py").exists() and (item / "myconfig.py").exists():
                        valid_projects.append(item)
        except Exception as e:
             console.print(f"[red]扫描出错: {e}[/red]")
             Prompt.ask("按回车键返回...")
             return

        if not valid_projects:
            console.print(f"[yellow]在 {base_dir} 下未找到有效的 DonkeyCar 项目。[/yellow]")
            Prompt.ask("按回车键返回...")
            return
            
        valid_projects.sort()

        console.print("[bold]发现以下有效项目:[/bold]")
        for idx, project_path in enumerate(valid_projects, 1):
            console.print(f"{idx}. {project_path.name}")
        
        console.print("\n[dim]提示: 输入编号选择项目，输入 '0' 取消[/dim]")
        
        while True:
            choice = Prompt.ask("请输入编号", default="0")
            if choice == "0":
                return
            elif choice.isdigit():
                idx = int(choice)
                if 1 <= idx <= len(valid_projects):
                    selected_project = valid_projects[idx-1]
                    try:
                        os.chdir(selected_project)
                        console.print(Panel(f"[bold green]✓ 已切换工作目录至: {selected_project}[/bold green]\n"
                                            f"[dim]现在您可以直接运行 train 或 drive 命令了[/dim]",
                                            title="项目切换成功"))
                    except Exception as e:
                        console.print(f"[red]切换目录失败: {e}[/red]")
                    Prompt.ask("按回车键返回菜单...")
                    return
            console.print("[red]无效的选择，请重新输入[/red]")

    def get_command_line(self, params):
        return [] # Not used since we override execute

class ClearDataCommand(DonkeyCommand):
    def __init__(self):
        super().__init__("clear_data", "清空当前项目 data 目录", "管理", is_favorite=False, requires_mycar_folder=True)
        self.options = []

    def execute(self):
        console.clear()
        console.print(Panel(f"[bold blue]{self.description}[/bold blue]", title=f"配置 {self.name}"))

        if self.requires_mycar_folder and not is_valid_mycar_folder():
            console.print(Panel(
                "[bold red]错误：当前目录不是有效的 mycar 项目文件夹！[/bold red]\n\n"
                "缺少关键文件：manage.py 或 myconfig.py\n"
                "请先执行 [bold yellow]createcar[/bold yellow] 命令创建新的车辆项目。",
                title="环境检查失败",
                border_style="red"
            ))
            Prompt.ask("按回车键返回菜单...")
            return

        data_dir = Path("./data")
        if not data_dir.exists():
            console.print(Panel("[yellow]未找到 data 目录，无需清空。[/yellow]", title="状态提示"))
            self.history_mgr.add_action_log("clear_data", "skipped", {"reason": "data_dir_missing"})
            Prompt.ask("按回车键返回菜单...")
            return

        file_count, total_size = _scan_directory(data_dir)
        top_level_items = [p for p in data_dir.iterdir()]
        if not top_level_items:
            console.print(Panel("[green]data 目录已为空，无需操作。[/green]", title="状态提示"))
            self.history_mgr.add_action_log("clear_data", "skipped", {"reason": "data_dir_empty"})
            Prompt.ask("按回车键返回菜单...")
            return

        console.print(Panel(
            f"[bold]即将清空目录:[/bold] {data_dir.resolve()}\n"
            f"[bold]文件数量:[/bold] {file_count}\n"
            f"[bold]总大小:[/bold] {_human_readable_size(total_size)}",
            title="操作确认",
            border_style="yellow"
        ))

        if not Confirm.ask("确认开始?", default=False):
            self.history_mgr.add_action_log("clear_data", "cancelled")
            return

        backup_path = None
        if Confirm.ask("是否创建备份（推荐）?", default=False):
            backup_dir = Path("./data_backups")
            backup_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            archive_base = backup_dir / f"data_backup_{timestamp}"
            try:
                console.print("[dim]正在创建备份...[/dim]")
                backup_path = shutil.make_archive(str(archive_base), "zip", root_dir=data_dir)
                console.print(f"[green]备份已创建: {backup_path}[/green]")
            except Exception as e:
                console.print(f"[red]备份失败: {e}[/red]")
                backup_path = None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        trash_dir = data_dir.parent / f".data_trash_{timestamp}"
        moved, move_errors = _move_items_to_trash(data_dir, trash_dir)

        if move_errors:
            _restore_from_trash(trash_dir, data_dir)
            console.print(Panel(
                "[red]移动数据到临时区失败，已尝试回滚。[/red]\n"
                + "\n".join(move_errors[:10]),
                title="操作失败",
                border_style="red"
            ))
            self.history_mgr.add_action_log("clear_data", "failed", {
                "stage": "move_to_trash",
                "errors": move_errors[:20]
            })
            Prompt.ask("按回车键返回菜单...")
            return

        total_files = file_count
        progress_queue: queue.Queue = queue.Queue()

        def worker():
            errors = _delete_directory_contents(trash_dir, lambda n: progress_queue.put(("progress", n)))
            progress_queue.put(("done", errors))

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        errors: List[str] = []
        with Progress(
            TextColumn("{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            TimeRemainingColumn()
        ) as progress:
            total = max(1, total_files)
            task_id = progress.add_task("正在清空 data...", total=total)
            while thread.is_alive() or not progress_queue.empty():
                try:
                    msg = progress_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                if msg[0] == "progress":
                    progress.advance(task_id, msg[1])
                elif msg[0] == "done":
                    errors = msg[1]
            if total_files == 0:
                progress.advance(task_id, 1)

        if not errors:
            try:
                shutil.rmtree(trash_dir, ignore_errors=False)
            except Exception as e:
                errors.append(f"{trash_dir}: {e}")

        if errors:
            restore_errors = _restore_from_trash(trash_dir, data_dir)
            detail = {
                "errors": errors[:20],
                "restore_errors": restore_errors[:20],
                "backup_path": backup_path
            }
            console.print(Panel(
                "[red]清空过程中出现错误，已尝试回滚未删除的数据。[/red]\n"
                "建议:\n"
                "- 关闭占用文件的进程后重试\n"
                "- 检查目录权限\n"
                + (f"\n- 如需完整恢复，请使用备份: {backup_path}" if backup_path else ""),
                title="部分失败",
                border_style="red"
            ))
            self.history_mgr.add_action_log("clear_data", "partial_failed", detail)
        else:
            console.print(Panel(
                "[bold green]✓ data 目录已清空[/bold green]",
                title="操作完成",
                border_style="green"
            ))
            self.history_mgr.add_action_log("clear_data", "success", {
                "files": file_count,
                "size": total_size,
                "backup_path": backup_path
            })

        Prompt.ask("按回车键返回菜单...")

from donkeycar.management.train_online import OnlineTrainer
from donkeycar.management.train_local import run_local_train

class TrainLocalCommand(DonkeyCommand):
    def __init__(self):
        super().__init__("train_local", "本地训练", "训练", is_favorite=True)
        self.options = [
            CommandOption("tub", "数据目录 (Tub)", default="./data", help_text="包含训练数据的目录"),
            CommandOption("model", "模型输出路径", default=self._get_next_model_name(), help_text="训练后的模型保存路径 (自动递增)"),
            CommandOption("type", "模型类型", default="linear", help_text="可选: linear, categorical, rnn, imu, behavior, localizer, 3d"),
            CommandOption("transfer", "迁移学习模型", default=None, required=False, help_text="基础模型路径 (可选)")
        ]

    def _get_next_model_name(self, base_name="pilot"):
        """
        生成下一个自动递增的模型名称。
        默认名称: ./models/pilot_1
        如果存在，则递增为 pilot_2, pilot_3 ...
        """
        models_dir = Path("./models")
        if not models_dir.exists():
            return f"./models/{base_name}_1"

        import re
        
        # 匹配 pilot_x 或 pilot_x.h5 的正则
        pattern = re.compile(rf"^{base_name}_(\d+)(?:\.h5)?$")
        
        max_idx = 0
        for f in models_dir.glob("*"):
            if f.is_file() and not f.name.startswith('.'):
                match = pattern.match(f.name)
                if match:
                    idx = int(match.group(1))
                    if idx > max_idx:
                        max_idx = idx
        
        next_idx = max_idx + 1
        return f"./models/{base_name}_{next_idx}"

    def execute(self):
        # Update default model name
        for opt in self.options:
            if opt.name == "model":
                opt.default = self._get_next_model_name()
                break
        
        # Reuse base class execution flow which calls get_command_line
        super().execute()

    def get_command_line(self, params):
        # We construct the command to run the script via python -m or direct
        # But actually, we can just return the donkey command as before, 
        # OR since we have run_local_train logic in a file, we could call it.
        # However, TUI executes via subprocess.
        # Let's keep using 'donkey train' as it's the standard way, 
        # AND the user requirement was to split the module, which we did.
        # But the prompt said "refactor... into train_online and train_local".
        # So maybe we should call our new script?
        # Let's call the original donkey train for local to be safe/standard, 
        # or call python donkeycar/management/train_local.py? 
        # calling `donkey train` IS running local training.
        # But let's stick to the prompt's implication of using the new modules.
        # Actually, `run_local_train` in `train_local.py` just calls `donkey train` subprocess.
        # So we can just use the command line directly here.
        
        cmd = ["donkey", "train", "--tub", params["tub"], "--model", params["model"], "--type", params["type"]]
        if params.get("transfer"):
            cmd.extend(["--transfer", params["transfer"]])
        return cmd

class TrainOnlineCommand(DonkeyCommand):
    def __init__(self):
        super().__init__("train_online", "云端训练（train_online.conf）", "训练", is_favorite=True)
        self.options = [] # Configuration is via file, not CLI args for simplicity as per requirements

    def execute(self):
        console.clear()
        console.print(Panel(f"[bold blue]{self.description}[/bold blue]", title=f"配置 {self.name}"))
        
        # Check env
        if self.requires_mycar_folder and not is_valid_mycar_folder():
             console.print("[red]请在有效的 mycar 项目目录下运行[/red]")
             Prompt.ask("按回车键返回...")
             return

        console.print("即将开始云端训练流程：打包 -> 上传 -> 训练 -> 下载")
        console.print("配置文件: train_online.conf (首次运行自动生成)")
        
        if not Confirm.ask("确认开始?", default=True):
            return

        try:
            # Call the OnlineTrainer logic directly
            trainer = OnlineTrainer()
            trainer.run()
        except Exception as e:
            console.print(f"[red]执行出错: {e}[/red]")
        
        Prompt.ask("\n按回车键返回菜单...")

    def get_command_line(self, params):
        return [] # Not used

class DriveCommand(DonkeyCommand):
    def __init__(self):
        super().__init__("drive", "启动驾驶模式", "驾驶", is_favorite=True)
        self.options = [
            CommandOption("model", "模型名称", default=None, required=False, help_text="请选择要加载的模型 (默认0:不加载)"),
            CommandOption("type", "模型类型", default="tflite_linear", required=False, help_text="模型类型 (默认: tflite_linear)")
        ]

    def execute(self):
        console.clear()
        console.print(Panel(f"[bold blue]{self.description}[/bold blue]", title=f"配置 {self.name}"))
        
        # 检查是否需要有效的 mycar 目录
        if self.requires_mycar_folder and not is_valid_mycar_folder():
            console.print(Panel(
                "[bold red]错误：当前目录不是有效的 mycar 项目文件夹！[/bold red]\n\n"
                "缺少关键文件：manage.py 或 myconfig.py\n"
                "请先执行 [bold yellow]createcar[/bold yellow] 命令创建新的车辆项目。",
                title="环境检查失败",
                border_style="red"
            ))
            Prompt.ask("按回车键返回菜单...")
            return

        last_params = self.history_mgr.get_last_params(self.name)
        current_params = {}

        # Custom logic for model selection
        models_dir = Path("./models")
        model_files = []
        if models_dir.exists():
            model_files = [f.name for f in models_dir.glob("*") if f.is_file() and not f.name.startswith('.')]
            model_files.sort()
        
        # Model selection
        console.print("[bold]选择模型:[/bold]")
        console.print("0. 不加载模型 (默认)")
        for idx, filename in enumerate(model_files, 1):
            console.print(f"{idx}. {filename}")
        
        while True:
            choice = Prompt.ask("请输入编号", default="0")
            if choice == "0":
                current_params["model"] = None
                break
            elif choice.isdigit():
                idx = int(choice)
                if 1 <= idx <= len(model_files):
                    current_params["model"] = model_files[idx-1]
                    break
            console.print("[red]无效的选择，请重新输入[/red]")

        # Other options
        # Skip the first option (model) as we handled it manually
        for opt in self.options[1:]:
            default_val = last_params.get(opt.name, opt.default)
            prompt_text = f"{opt.prompt_text}"
            if opt.help_text:
                console.print(f"[dim]{opt.help_text}[/dim]")
            
            while True:
                val = Prompt.ask(prompt_text, default=str(default_val) if default_val is not None else None)
                if not val and opt.required and default_val is None:
                    console.print("[red]此项为必填项[/red]")
                    continue
                
                if opt.validator and val:
                    if not opt.validator(val):
                        console.print(f"[red]输入无效，请重新输入[/red]")
                        continue
                
                current_params[opt.name] = val
                break

        # Generate preview
        cmd_list = self.get_command_line(current_params)
        cmd_str = " ".join(cmd_list)
        
        console.print("\n[bold yellow]命令预览:[/bold yellow]")
        console.print(Panel(f"[green]{cmd_str}[/green]", title="Shell Command"))

        # Confirm execution
        console.print("([green]y[/green]:执行 [red]n[/red]:取消 [blue]c[/blue]:复制命令)")
        action = Prompt.ask(
            "请选择操作", 
            choices=["y", "n", "c", "copy"], 
            default="y",
            show_choices=False
        )

        if action == "copy":
            import pyperclip
            try:
                pyperclip.copy(cmd_str)
                console.print("[green]✓ 命令已复制到剪贴板[/green]")
            except ImportError:
                console.print("[red]✗ 未安装 pyperclip，无法复制。请手动复制上方命令。[/red]")
            Prompt.ask("按回车键返回...")
            return

        if action != "y":
            console.print("[yellow]操作已取消[/yellow]")
            time.sleep(1)
            return

        # Execute and log
        self.history_mgr.update_last_params(self.name, current_params)
        self.history_mgr.add_command_log(cmd_str)
        
        console.print(f"\n[bold cyan]>> [{datetime.now().strftime('%H:%M:%S')}] 开始执行...[/bold cyan]")
        console.print("[bold yellow]提示: 按 ESC 键停止运行并返回菜单[/bold yellow]")
        
        try:
            # 针对 Windows 和其他系统的处理
            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP
            
            process = subprocess.Popen(
                cmd_list, 
                stdout=sys.stdout, 
                stderr=sys.stderr,
                text=True,
                creationflags=creation_flags
            )
            
            # 键盘监听循环
            import signal
            import select
            
            # Windows 键盘监听
            def is_esc_pressed_win():
                try:
                    import msvcrt
                    if msvcrt.kbhit():
                        if ord(msvcrt.getch()) == 27: # ESC
                            return True
                except ImportError:
                    pass
                return False

            # Linux/Mac 键盘监听
            def is_esc_pressed_unix():
                try:
                    import sys
                    import termios
                    import tty
                    
                    # 检查 stdin 是否有数据
                    if select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], []):
                        c = sys.stdin.read(1)
                        if c == '\x1b': # ESC
                            return True
                except ImportError:
                    pass
                return False

            # 保存终端设置 (仅限 Unix)
            old_settings = None
            if sys.platform != "win32":
                try:
                    import termios
                    import tty
                    old_settings = termios.tcgetattr(sys.stdin)
                    tty.setcbreak(sys.stdin.fileno())
                except Exception:
                    pass

            try:
                while process.poll() is None:
                    esc_pressed = False
                    if sys.platform == "win32":
                        esc_pressed = is_esc_pressed_win()
                    else:
                        esc_pressed = is_esc_pressed_unix()

                    if esc_pressed:
                        console.print("\n[yellow]检测到 ESC 键，正在停止...[/yellow]")
                        if sys.platform == "win32":
                            os.kill(process.pid, signal.CTRL_C_EVENT)
                        else:
                            process.send_signal(signal.SIGINT)
                        
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            process.kill()
                        break
                    
                    # 避免 CPU 占用过高
                    time.sleep(0.1)
            finally:
                # 恢复终端设置 (仅限 Unix)
                if old_settings:
                    import termios
                    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)

            if process.poll() is None:
                # 如果还没有结束（非 ESC 退出，或者 Linux 环境），继续等待
                process.wait()
            
            if process.returncode == 0 or process.returncode == 3221225786: # 3221225786 is CTRL+C on Windows
                console.print(f"\n[bold green]✓ 执行结束[/bold green]")
            else:
                console.print(f"\n[bold red]✗ 执行失败 (Exit Code: {process.returncode})[/bold red]")
                console.print(f"[dim]请检查上方错误日志[/dim]")

        except KeyboardInterrupt:
            # 捕获父进程的 Ctrl+C，尝试优雅关闭子进程
            console.print("\n[yellow]收到中断信号，正在停止...[/yellow]")
            if process and process.poll() is None:
                if sys.platform == "win32":
                    os.kill(process.pid, signal.CTRL_C_EVENT)
                else:
                    process.send_signal(signal.SIGINT)
                process.wait()
        except Exception as e:
            console.print(f"\n[bold red]✗ 发生异常: {e}[/bold red]")
        
        Prompt.ask("\n按回车键返回菜单...")

    def get_command_line(self, params):
        # 优先使用当前目录的 manage.py
        if os.path.exists("manage.py"):
            cmd = [sys.executable, "manage.py", "drive"]
        else:
            cmd = ["donkey", "ui"] # Fallback

        if params.get("model"):
            full_model_path = os.path.join("./models", params["model"])
            cmd.extend(["--model", full_model_path])
        if params.get("type"):
            cmd.extend(["--type", params["type"]])
        return cmd

# -----------------------------------------------------------------------------
# 菜单系统
# -----------------------------------------------------------------------------
class MenuSystem:
    def __init__(self):
        self.commands: Dict[str, List[DonkeyCommand]] = {
            "管理": [CreateCarCommand(), OpenProjectCommand(), ClearDataCommand()],
            "驾驶": [DriveCommand()],
            "训练": [TrainLocalCommand(), TrainOnlineCommand()],
        }
        self.flat_commands = [cmd for sublist in self.commands.values() for cmd in sublist]

    def show_main_menu(self):
        while True:
            console.clear()
            self._print_header()
            
            # 显示最近使用记录 (可选)
            # self._print_recent_history()

            table = Table(box=box.ROUNDED, show_header=True, header_style="bold magenta")
            table.add_column("No.", style="cyan", width=4, justify="right")
            table.add_column("分类", style="bold yellow", width=8)
            table.add_column("功能名称", style="green", width=20)
            table.add_column("描述", style="dim")

            menu_items = []
            idx = 1
            
            for category, cmds in self.commands.items():
                first = True
                for cmd in cmds:
                    # 标记常用功能
                    name_display = f"{cmd.name} [*]" if cmd.is_favorite else cmd.name
                    cat_display = category if first else ""
                    
                    table.add_row(str(idx), cat_display, name_display, cmd.description)
                    menu_items.append(cmd)
                    idx += 1
                    first = False
                table.add_section()

            console.print(table)
            console.print("[dim]提示: 输入编号选择功能，输入 '?' 显示帮助，输入 '0' 退出[/dim]")

            choice = Prompt.ask("\n请选择", default="0")

            if choice == "0":
                if Confirm.ask("确定要退出吗?"):
                    console.print("再见! 👋")
                    sys.exit(0)
            elif choice == "?":
                self.show_help()
            elif choice.isdigit():
                c_idx = int(choice) - 1
                if 0 <= c_idx < len(menu_items):
                    menu_items[c_idx].execute()
                else:
                    console.print(f"[red]无效的编号: {choice}[/red]")
                    time.sleep(1)
            else:
                console.print(f"[red]无效输入[/red]")
                time.sleep(1)

    def _print_header(self):
        title = Text("Donkey Car 交互式管理终端", style="bold white on blue", justify="center")
        console.print(Panel(title, style="blue"))
        console.print(f"[dim]当前目录: {os.getcwd()}[/dim]\n")

    def show_help(self):
        console.clear()
        md = Markdown("""
# 帮助系统

此工具旨在简化 Donkey Car 的命令行操作。

## 操作指南
- **输入编号**: 直接输入菜单左侧的数字进入相应功能。
- **参数输入**: 进入功能后，根据提示输入参数。[]内为默认值，直接回车即可使用。
- **常用功能**: 带 `*` 标记的为常用功能。
- **历史记录**: 您的输入会被自动记录，下次使用时作为默认值。

## 常见问题
- 如果 `donkey` 命令未找到，请确保已激活 conda 环境。
- 只有在确认页面输入 `y` 才会真正执行命令。
        """)
        console.print(Panel(md, title="帮助说明", border_style="green"))
        Prompt.ask("按回车键返回...")

# -----------------------------------------------------------------------------
# 入口
# -----------------------------------------------------------------------------
def main():
    try:
        app = MenuSystem()
        app.show_main_menu()
    except KeyboardInterrupt:
        console.print("\n[yellow]程序已中断[/yellow]")
        sys.exit(0)

if __name__ == "__main__":
    main()
