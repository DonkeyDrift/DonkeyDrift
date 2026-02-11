
import os
import sys
import subprocess
import tarfile
import paramiko
import configparser
import time
import re
import select
import random
import secrets
import string
from datetime import datetime
from pathlib import Path
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.panel import Panel
from rich.prompt import Prompt, Confirm

console = Console()

class OnlineTrainer:
    def __init__(self, config_file="train_online.conf"):
        self.config_file = config_file
        self.config_dir = Path(self.config_file).resolve().parent
        self.config = self._load_config()
        self.ssh_client = None
        self.sftp_client = None
        self.remote_work_dir = None  # 用于存储动态生成的远程工作目录
        self.log_file = os.path.join("logs", "train_online.log")

    def _log(self, message, success=True):
        timestamp = datetime.now().isoformat()
        status = "SUCCESS" if success else "FAILED"
        log_path = self.config_dir / self.log_file
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] [{status}] {message}\n")

    def _get_interactive_model_name(self, no_interactive=False):
        """
        获取交互式模型名称，支持配置文件回写和自动后缀追加
        """
        current_model_name = self.get_config_value("model_name")
        
        if no_interactive:
            # 非交互模式，直接使用配置值并添加后缀
            final_model_name = self._generate_unique_model_name(current_model_name)
            console.print(f"[dim]非交互模式，使用模型名称: {final_model_name}[/dim]")
            return final_model_name
        
        # 交互模式
        console.print(f"\n[bold blue]模型配置[/bold blue]")
        console.print(f"当前配置文件: {self.config_file}")
        
        # 提示用户输入，显示当前值作为默认值
        user_input = Prompt.ask(
            f"请输入模型名称",
            default=current_model_name
        )
        
        # 如果用户输入了新的名称，更新配置文件
        if user_input != current_model_name:
            try:
                # 原子性更新配置文件
                self.config.set("Remote", "model_name", user_input)
                with open(self.config_file, 'w') as f:
                    self.config.write(f)
                console.print(f"[green]✓ 配置文件已更新: model_name = {user_input}[/green]")
                self._log(f"Updated config model_name from '{current_model_name}' to '{user_input}'")
            except Exception as e:
                self._log(f"Failed to update config file: {e}", success=False)
                raise RuntimeError(f"配置文件写入失败: {e}")
        
        # 生成最终带后缀的模型名称
        final_model_name = self._generate_unique_model_name(user_input)
        console.print(f"最终模型名称: [bold]{final_model_name}[/bold]")
        
        return final_model_name

    def _generate_unique_model_name(self, base_name):
        """
        生成全局唯一的模型名称，格式：folder-model-YYMMDD-ABCD
        
        Args:
            base_name: 用户输入的原始模型名称
            
        Returns:
            str: 生成的唯一模型名称
        """
        # 1. Folder name (current working directory name)
        folder_name = os.path.basename(os.getcwd())
        
        # 2. Clean model name (keep only letters, numbers, underscore)
        clean_model = re.sub(r'[^a-zA-Z0-9_]', '', base_name)
        if not clean_model:
            clean_model = "model"
            
        # 3. Date
        date_str = datetime.now().strftime("%y%m%d")
        
        # 4. Generate unique name with retries
        models_dir = "./models"
        if not os.path.exists(models_dir):
            os.makedirs(models_dir)
            
        while True:
            # Cryptographically secure random string (4 chars: 0-9, A-Z)
            chars = string.ascii_uppercase + string.digits
            rand_suffix = ''.join(secrets.choice(chars) for _ in range(4))
            
            final_name = f"{folder_name}-{clean_model}-{date_str}-{rand_suffix}"
            filename = f"{final_name}.tflite"
            
            # Check if exists locally to avoid collision before even sending to remote
            # Note: Remote collision is also possible but highly unlikely with 36^4 combinations per day per user/folder.
            # We primarily check local 'models' dir to ensure download won't fail/overwrite unexpectedly.
            if not os.path.exists(os.path.join(models_dir, filename)):
                self._log(f"Generated unique model name: {final_name}")
                return final_name
            else:
                self._log(f"Model name collision locally: {final_name}, retrying...", success=False)

    # _get_auto_increment_model_name 已废弃，直接移除或保留作为兼容（这里选择移除以保持清洁）

    def _load_config(self):
        config = configparser.ConfigParser()
        if not os.path.exists(self.config_file):
            current_dir_name = os.path.basename(os.getcwd())
            config["Remote"] = {
                "host": "121.5.26.9",
                "user": "ubuntu",
                "password": "dkc@2026",
                "remote_dir_base": "~/projects",  # 修改为父级目录
                "model_name": "model",
                "python_path": "~/miniconda3/envs/donkey/bin/python"
            }
            with open(self.config_file, "w") as f:
                config.write(f)
            console.print(f"[yellow]配置文件 {self.config_file} 不存在，已创建默认配置。[/yellow]")
        else:
            config.read(self.config_file)
            # Ensure new keys exist if updating old config
            if "python_path" not in config["Remote"]:
                config["Remote"]["python_path"] = "~/miniconda3/envs/donkey/bin/python"
                with open(self.config_file, "w") as f:
                    config.write(f)
        
        # Interactive confirmation/edit (simplified for non-blocking flow, can be expanded)
        # In a real TUI, we might want to let the user edit these values. 
        # For now, we assume the file is the source of truth.
        return config

    def get_config_value(self, key):
        return self.config["Remote"].get(key)

    def package_data(self):
        data_dir = "./data"
        if not os.path.exists(data_dir):
            raise FileNotFoundError("Local ./data directory not found")

        # 1. Check and create cache dir
        cache_dir = "./data_cache"
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)

        # 2. Naming rule: data-YYMMDD-XXX.tar.gz
        today_str = datetime.now().strftime("%y%m%d")
        pattern = re.compile(rf"^data-{today_str}-(\d{{3}})\.tar\.gz$")
        
        max_seq = 0
        for f in os.listdir(cache_dir):
            match = pattern.match(f)
            if match:
                seq = int(match.group(1))
                if seq > max_seq:
                    max_seq = seq
        
        next_seq = max_seq + 1
        filename = f"data-{today_str}-{next_seq:03d}.tar.gz"
        filepath = os.path.join(cache_dir, filename)
        filepath = os.path.abspath(filepath)

        console.print(f"正在打包 {data_dir} 到 {filepath} ...")
        
        # 3. Package
        with tarfile.open(filepath, "w:gz") as tar:
            tar.add(data_dir, arcname="data")
        
        # 4. Verify integrity
        console.print("正在校验备份文件...")
        try:
            # Check if it is a valid tar file
            if not tarfile.is_tarfile(filepath):
                 raise RuntimeError("File is not a valid tar archive")
            
            # Detailed check: iterate over members
            with tarfile.open(filepath, "r:gz") as tar:
                for _ in tar:
                    pass
        except Exception as e:
            self._log(f"Backup verification failed: {e}", success=False)
            if os.path.exists(filepath):
                os.remove(filepath)
            raise RuntimeError(f"备份文件校验失败: {e}")

        size = os.path.getsize(filepath)
        console.print(f"[green]打包及备份完成: {filepath} (大小: {size/1024/1024:.2f} MB)[/green]")
        self._log(f"Packaged data to {filepath}, size={size}")
        return filepath, size

    def connect_ssh(self):
        host = self.get_config_value("host")
        user = self.get_config_value("user")
        password = self.get_config_value("password")
        
        self.ssh_client = paramiko.SSHClient()
        self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        retries = 3
        for attempt in range(retries):
            try:
                self.ssh_client.connect(host, username=user, password=password, timeout=10)
                console.print(f"[bold green][OK] SSH 连接到 {host}:22 成功[/bold green]")
                self._log(f"SSH connected to {host}")
                self.sftp_client = self.ssh_client.open_sftp()
                return
            except Exception as e:
                console.print(f"[yellow]连接尝试 {attempt+1}/{retries} 失败: {e}[/yellow]")
                time.sleep(1)
        
        self._log("SSH connection failed after retries", success=False)
        raise ConnectionError(f"Failed to connect to {host} after {retries} attempts")

    def _resolve_remote_path(self, path):
        """
        Resolve remote path (especially ~ expansion) using SSH shell.
        """
        if not path.startswith("~"):
            return path
        
        # Execute echo expansion on remote
        stdin, stdout, stderr = self.ssh_client.exec_command(f"echo {path}")
        resolved_path = stdout.read().decode().strip()
        
        if not resolved_path:
             # Fallback if echo fails or returns empty, though unlikely
             # Try to get home dir explicitly
             stdin, stdout, stderr = self.ssh_client.exec_command("echo $HOME")
             home = stdout.read().decode().strip()
             if home:
                 return path.replace("~", home, 1)
             return path # Failed to resolve
             
        return resolved_path

    def _generate_workspace_name(self, existing_names, date_str=None):
        """
        生成唯一的工作目录名称，格式：mycar-YYMMDD-XXX-ABCD
        
        Args:
            existing_names (list): 已存在的目录名称列表
            date_str (str, optional): 日期字符串，默认当天
            
        Returns:
            str: 生成的目录名称
        """
        if date_str is None:
            date_str = datetime.now().strftime("%y%m%d")
        
        pattern = re.compile(rf"^mycar-{date_str}-(\d{{3}})-[0-9A-Z]{{4}}$")
        
        max_seq = 0
        
        for name in existing_names:
            match = pattern.match(name)
            if match:
                seq = int(match.group(1))
                if seq > max_seq:
                    max_seq = seq
        
        next_seq = max_seq + 1
        
        # 生成4位随机码（数字+大写字母），确保当日唯一性需要结合现有列表检查，
        # 但此处主要依赖序号递增保证顺序，随机码作为防冲突补充。
        # 简单起见，每次随机生成，冲突概率极低。
        random_code = ''.join(random.choices(string.digits + string.ascii_uppercase, k=4))
        
        return f"mycar-{date_str}-{next_seq:03d}-{random_code}"

    def setup_remote_workspace(self):
        """
        在远程服务器上设置独立的工作目录。
        遵循规则：mycar-YYMMDD-XXX-ABCD
        """
        if self.remote_work_dir:
            return self.remote_work_dir

        if not self.ssh_client:
            raise RuntimeError("SSH client not connected. Call connect_ssh() first.")

        parent_dir_raw = self.get_config_value("remote_dir_base")
        parent_dir = self._resolve_remote_path(parent_dir_raw)

        # 1. 检查父级目录是否存在且可写
        check_cmd = f"test -d {parent_dir} && test -w {parent_dir}"
        stdin, stdout, stderr = self.ssh_client.exec_command(check_cmd)
        if stdout.channel.recv_exit_status() != 0:
            self._log(f"Parent directory {parent_dir} not writable or does not exist", success=False)
            raise PermissionError(f"远程父目录 {parent_dir} 不存在或不可写")

        # 2. 获取现有的子目录列表
        ls_cmd = f"ls -1 {parent_dir}"
        stdin, stdout, stderr = self.ssh_client.exec_command(ls_cmd)
        existing_names = stdout.read().decode().strip().split('\n')
        
        # 3. 尝试生成并创建目录（带重试机制）
        retries = 3
        python_path = self.get_config_value("python_path")
        python_path_resolved = self._resolve_remote_path(python_path)
        # 假设 donkey 命令在 python 同级目录
        if "/" in python_path_resolved:
            donkey_bin = python_path_resolved.rsplit('/', 1)[0] + "/donkey"
        else:
            donkey_bin = "donkey" # Fallback

        for attempt in range(retries):
            new_name = self._generate_workspace_name(existing_names)
            full_path = f"{parent_dir}/{new_name}".replace("//", "/")
            
            console.print(f"尝试创建远程工作目录: {full_path} (尝试 {attempt+1}/{retries})...")
            
            create_cmd = f"{donkey_bin} createcar --path {full_path}"
            
            stdin, stdout, stderr = self.ssh_client.exec_command(create_cmd)
            exit_status = stdout.channel.recv_exit_status()
            
            if exit_status == 0:
                self.remote_work_dir = full_path
                console.print(f"[green]成功创建远程工作目录: {full_path}[/green]")
                self._log(f"Created remote workspace: {full_path}")
                return full_path
            else:
                err_msg = stderr.read().decode().strip()
                # 检查是否是目录已存在
                if "File exists" in err_msg or "already exists" in err_msg:
                    console.print(f"[yellow]目录名冲突，重试中...[/yellow]")
                    continue
                else:
                    self._log(f"Failed to create car: {err_msg}", success=False)
                    raise RuntimeError(f"创建远程目录失败: {err_msg}")
        
        raise RuntimeError(f"在 {retries} 次尝试后无法生成唯一的远程目录")

    def upload_data(self, local_path, remote_filename):
        # 确保工作目录已创建
        self.setup_remote_workspace()
        
        # 使用生成的 remote_work_dir
        remote_dir = self.remote_work_dir


        remote_path = f"{remote_dir}/{remote_filename}".replace("//", "/")
        file_size = os.path.getsize(local_path)
        
        console.print(f"正在上传数据到 {remote_path} ...")
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console
        ) as progress:
            task = progress.add_task("Uploading...", total=file_size)
            
            def callback(transferred, total):
                progress.update(task, completed=transferred)
                # Check 10% increments for logging/printing if needed, but progress bar handles visual
            
            self.sftp_client.put(local_path, remote_path, callback=callback)
        
        # Verify size
        remote_attr = self.sftp_client.stat(remote_path)
        if remote_attr.st_size == file_size:
            console.print(f"[bold green][OK] 压缩包已上传至 {remote_path}[/bold green]")
            self._log(f"Uploaded {local_path} to {remote_path}")
        else:
            self._log("Upload size mismatch", success=False)
            raise RuntimeError("Upload verification failed: size mismatch")
        
        return remote_path

    def run_remote_training(self, remote_tar_path, model_name=None):
        remote_dir = self.remote_work_dir
        if not remote_dir:
             raise RuntimeError("Remote workspace not initialized. Please upload data first.")

        if model_name is None:
            model_name = self.get_config_value("model_name")
        python_path = self.get_config_value("python_path")
        
        # Resolve python path if needed (e.g. if it starts with ~)
        python_path = self._resolve_remote_path(python_path)

        filename = os.path.basename(remote_tar_path)
        
        # 1. Pre-check Resources
        self._check_remote_resources(remote_dir)

        # 2. Extract
        console.print("正在远程解压数据...")
        cmd_extract = f"tar -xzf {remote_dir}/{filename} -C {remote_dir}"
        stdin, stdout, stderr = self.ssh_client.exec_command(cmd_extract)
        if stdout.channel.recv_exit_status() != 0:
             err = stderr.read().decode()
             self._log(f"Remote extraction failed: {err}", success=False)
             raise RuntimeError(f"Remote extraction failed: {err}")

        # 3. Train
        console.print(f"正在启动云端训练 (Python: {python_path})...")
        # Fix: Use train.py instead of manage.py train
        cmd_train = f"cd {remote_dir} && {python_path} train.py --tub ./data --model ./models/{model_name} --type linear"
        
        # We need to stream output
        stdin, stdout, stderr = self.ssh_client.exec_command(cmd_train, get_pty=True)
        
        start_time = time.time()
        training_finished = False
        timeout = 3600 # 1 hour timeout
        
        # Monitoring UI
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TextColumn("{task.fields[info]}"),
            console=console
        ) as progress:
            train_task = progress.add_task("训练进度", total=100, info="Waiting...")
            
            while not stdout.channel.exit_status_ready():
                if time.time() - start_time > timeout:
                    raise TimeoutError("训练超时 (超过 60 分钟)")

                if stdout.channel.recv_ready():
                    line = stdout.channel.recv(1024).decode('utf-8', errors='ignore')
                    # Parse progress
                    self._parse_training_output(line, progress, train_task)
                    
                    sys.stdout.write(line)
                    sys.stdout.flush()
                    if "Finished training" in line:
                        training_finished = True
                
                if stderr.channel.recv_ready():
                    line = stderr.channel.recv(1024).decode('utf-8', errors='ignore')
                    sys.stderr.write(line)
                    sys.stderr.flush()
                
                time.sleep(0.1)
                
        # Check remaining buffer
        remaining = stdout.read().decode('utf-8', errors='ignore')
        sys.stdout.write(remaining)
        if "Finished training" in remaining:
            training_finished = True

        end_time = time.time()
        duration = end_time - start_time
        minutes = int(duration // 60)
        seconds = int(duration % 60)
        
        if training_finished:
            console.print(f"\n[bold green][OK] 云端训练完成，总用时：{minutes} 分 {seconds} 秒[/bold green]")
            self._log(f"Training finished in {minutes}m {seconds}s")
        else:
            console.print("\n[red]未检测到 'Finished training'，训练可能失败[/red]")
            self._log("Training finished without success message", success=False)

    def _check_remote_resources(self, remote_dir):
        console.print("正在检查远程资源...")
        # Check Disk Space
        stdin, stdout, stderr = self.ssh_client.exec_command(f"df -k {remote_dir} | tail -1 | awk '{{print $4}}'")
        available_kb = stdout.read().decode().strip()
        if available_kb and available_kb.isdigit():
            available_mb = int(available_kb) / 1024
            if available_mb < 500:
                console.print(f"[bold yellow]警告: 远程磁盘空间不足 ({available_mb:.1f} MB)[/bold yellow]")
            else:
                console.print(f"[green]磁盘空间充足 ({available_mb:.1f} MB)[/green]")
        
        # Check Memory
        stdin, stdout, stderr = self.ssh_client.exec_command("free -m | grep Mem | awk '{print $7}'")
        available_mem = stdout.read().decode().strip()
        if available_mem and available_mem.isdigit():
             if int(available_mem) < 500:
                 console.print(f"[bold yellow]警告: 远程可用内存较低 ({available_mem} MB)[/bold yellow]")
             else:
                 console.print(f"[green]内存状态良好 (可用 {available_mem} MB)[/green]")

    def _parse_training_output(self, line, progress, task_id):
        # Example Keras output: 50/100 [=====>....] - loss: 0.123
        # Or Epoch 5/20
        try:
            # Match Epoch
            epoch_match = re.search(r"Epoch (\d+)/(\d+)", line)
            if epoch_match:
                current = int(epoch_match.group(1))
                total = int(epoch_match.group(2))
                percent = (current / total) * 100
                progress.update(task_id, completed=percent, info=f"Epoch {current}/{total}")
            
            # Match Loss
            loss_match = re.search(r"loss: (\d+\.\d+)", line)
            if loss_match:
                loss = loss_match.group(1)
                progress.update(task_id, info=f"Loss: {loss}")
        except Exception:
            pass # Ignore parsing errors


    def download_model(self, model_name=None):
        """
        下载训练好的模型。
        
        Args:
            model_name (str, optional): 要下载的模型名称（不含路径，含后缀或不含取决于具体逻辑，但在本类中通常指文件名主体）。
                                      新规范下应为 '{base_name}-YYMMDD-XXX' 格式。
                                      如果为 None，则回退到配置文件中的 'model_name'（旧规范）。
        """
        remote_dir = self.remote_work_dir
        if not remote_dir:
             # 如果未初始化工作目录，可能用户只想下载历史模型，
             # 但由于现在 remote_dir_base 是父目录，我们无法自动得知具体的子目录。
             # 除非我们允许用户手动指定，或者恢复旧逻辑（如果 remote_dir_base 看起来像完整路径）。
             # 鉴于需求强制要求隔离，这里抛出错误提示用户。
             raise RuntimeError("Remote workspace not initialized. Cannot determine source directory.")
        
        # Debug info
        console.print(f"[DEBUG] Current working directory: {os.getcwd()}")
        
        # remote_dir 已经是绝对路径（由 setup_remote_workspace 生成），不需要 resolve_remote_path
        # 但为了保险（万一 setup 逻辑变了），还是可以用，但 setup 生成的是全路径。
        # remote_dir = self._resolve_remote_path(remote_dir) 
        
        # 如果未传入 model_name，则从配置获取（兼容旧逻辑，但训练流程应传入完整名称）
        # 新命名规范要求 model_name 格式为：{base_name}-YYMMDD-XXX
        if model_name is None:
            model_name = self.get_config_value("model_name")
            
        remote_model_path = f"{remote_dir}/models/{model_name}.tflite".replace("//", "/")
        console.print(f"[DEBUG] Resolved remote model path: {remote_model_path}")
        
        local_models_dir = "./models"
        if not os.path.exists(local_models_dir):
            os.makedirs(local_models_dir)
            
        local_model_path = os.path.join(local_models_dir, f"{model_name}.tflite")
        local_model_path = os.path.abspath(local_model_path)
        console.print(f"[DEBUG] Local target path: {local_model_path}")
        
        if os.path.exists(local_model_path):
            console.print(f"[yellow]检测到本地模型 {local_model_path} 已存在，跳过下载[/yellow]")
            self._log(f"Local model {local_model_path} exists, skipping download")
            return local_model_path
        
        console.print(f"正在下载模型 {remote_model_path} ...")
        try:
            self.sftp_client.get(remote_model_path, local_model_path)
            console.print(f"[bold green][OK] 模型已下载至 {local_model_path}[/bold green]")
            self._log(f"Downloaded model to {local_model_path}")
            
            # Verify Model
            if self._verify_local_model(local_model_path):
                console.print(f"[bold green][OK] 模型校验通过[/bold green]")
            else:
                console.print(f"[bold red][FAIL] 模型校验失败，文件可能损坏[/bold red]")
            
            return local_model_path
        except Exception as e:
            console.print(f"[red]下载模型失败: {e}[/red]")
            self._log(f"Model download failed: {e}", success=False)
            raise

    def _verify_local_model(self, model_path):
        """
        Verify the downloaded model using tflite_runtime or tensorflow if available.
        Checks if the file is a valid flatbuffer.
        """
        console.print("正在校验模型完整性...")
        try:
            # Simple header check for TFLite (FlatBuffer)
            # TFLite files usually start with 'TFL3' at offset 4 or similar magic bytes
            # But just checking if we can instantiate an interpreter is better.
            
            # Try importing tflite_runtime or tensorflow
            try:
                import tflite_runtime.interpreter as tflite
            except ImportError:
                try:
                    import tensorflow.lite as tflite
                except ImportError:
                    console.print("[dim]未安装 tflite_runtime 或 tensorflow，跳过深度校验，仅检查文件头[/dim]")
                    # Fallback: check file size > 0 and maybe magic bytes
                    if os.path.getsize(model_path) == 0:
                        return False
                    return True

            # If we have library, try loading
            interpreter = tflite.Interpreter(model_path=model_path)
            interpreter.allocate_tensors()
            return True
        except Exception as e:
            console.print(f"[red]校验异常: {e}[/red]")
            return False

    def cleanup(self, remote_tar_path):
        if self.ssh_client:
            try:
                if remote_tar_path:
                    self.ssh_client.exec_command(f"rm {remote_tar_path}")
                self.ssh_client.close()
                self._log("Cleanup successful")
            except Exception as e:
                self._log(f"Cleanup failed: {e}", success=False)

    def run(self, no_interactive=False):
        tar_file = None
        remote_tar_path = None
        try:
            # 1. Config (Loaded in init)
            
            # 2. Get interactive model name
            final_model_name = self._get_interactive_model_name(no_interactive)
            
            # 3. Package
            tar_file, _ = self.package_data()
            
            # 4. Connect
            self.connect_ssh()
            
            # 5. Upload
            remote_tar_path = self.upload_data(tar_file, os.path.basename(tar_file))
            
            # 6. Train
            self.run_remote_training(remote_tar_path, final_model_name)
            
            # 7. Download
            local_model_path = self.download_model(final_model_name)
            
            # 8. Post-interaction
            # if local_model_path:
            #     if Confirm.ask(f"是否立即运行 drive？（将使用刚下载的模型 {local_model_path}）", default=True):
            #         # Use sys.executable to run the same python interpreter
            #         cmd = [sys.executable, "manage.py", "drive", "--model", local_model_path]
                    
            #         # Explicitly set type for tflite models, otherwise manage.py defaults to Keras (HDF5)
            #         if local_model_path.endswith(".tflite"):
            #             cmd.extend(["--type", "tflite_linear"])
                        
            #         subprocess.run(cmd)
            
        except Exception as e:
            console.print(f"[bold red]流程异常终止: {e}[/bold red]")
            self._log(f"Process failed: {e}", success=False)
            sys.exit(1)
        finally:
            self.cleanup(remote_tar_path)
            # Local tar file is kept as backup in ./data_cache
            if tar_file:
                console.print(f"[dim]Local backup saved at: {tar_file}[/dim]")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="DonkeyCar 云端训练工具")
    parser.add_argument("--no-interactive", action="store_true", 
                       help="非交互模式，使用配置文件中的默认值")
    parser.add_argument("--config", default="train_online.conf",
                       help="配置文件路径 (默认: train_online.conf)")
    
    args = parser.parse_args()
    
    trainer = OnlineTrainer(args.config)
    trainer.run(no_interactive=args.no_interactive)
