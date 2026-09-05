"""
WebOnlineTrainer - Adapts OnlineTrainer for web UI streaming.
Replaces Rich console output with queue-based logging.
"""
import os
import queue
import re
import time
from typing import Optional

from donkeycar.management.train_online import OnlineTrainer

from trainer_session import save_session


# Regex to strip ANSI escape codes (colour, cursor movement, etc.)
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


def _clean_line(raw: str) -> str:
    """Remove ANSI escape codes and surrounding whitespace."""
    return _ANSI_RE.sub('', raw).strip()


def _is_progress_bar_line(line: str) -> bool:
    """判断是否为 Keras 进度条行（Keras 2 的 [===>...] 与 Keras 3 的 ━━━ 粗线）。"""
    return "ETA:" in line or "━" in line or ("[" in line and "]" in line and "=" in line)


class WebOnlineTrainer(OnlineTrainer):
    """OnlineTrainer subclass that streams output to a queue instead of Rich console."""

    def __init__(self, config_file="train_online.conf",
                 log_queue: Optional[queue.Queue] = None,
                 working_dir: Optional[str] = None,
                 ssh_credentials: Optional[dict] = None,
                 tub: Optional[str] = None):
        self._log_queue = log_queue
        self._working_dir = working_dir or os.getcwd()
        self._ssh_credentials = ssh_credentials
        # 最近一条失败日志（_log(success=False) 的 message），run() 据此还原真实失败原因
        self._last_error: Optional[str] = None
        # 用户点「停止」时由 abort_remote() 置位：尚未进入训练命令的执行点
        # （打包/上传阶段）据此在执行训练前自行中止，避免远程留下孤儿进程
        self._abort_requested = False
        # Ensure CWD-sensitive operations use the correct directory
        old_cwd = os.getcwd()
        try:
            os.chdir(self._working_dir)
            super().__init__(config_file)
        finally:
            os.chdir(old_cwd)
        # mypc 模式支持前端指定 tub 相对路径（相对 working_dir，
        # 在 package_data 的 chdir 之后解析）
        if tub:
            self.data_dir = tub

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _emit(self, message: str, level: str = "info"):
        if self._log_queue is not None:
            self._log_queue.put({
                "type": "log",
                "line": message,
                "level": level,
                "timestamp": time.time()
            })

    def _emit_progress(self, percent: float, current_epoch: int, total_epochs: int,
                       current_step: int, total_steps: int, loss: Optional[float]):
        if self._log_queue is not None:
            self._log_queue.put({
                "type": "progress",
                "data": {
                    "globalPercent": percent,
                    "currentEpoch": current_epoch,
                    "totalEpochs": total_epochs,
                    "currentStep": current_step,
                    "totalSteps": total_steps,
                    "loss": loss,
                }
            })

    # ------------------------------------------------------------------
    # Overrides for CWD-sensitive methods
    # ------------------------------------------------------------------
    def _load_config(self):
        old = os.getcwd()
        try:
            os.chdir(self._working_dir)
            return super()._load_config()
        finally:
            os.chdir(old)

    def _log(self, message, success=True):
        super()._log(message, success)
        if not success:
            # 父类 run() 失败时会 _log(f"Process failed: {e}", success=False)，
            # 记下来供 run() 把 SystemExit 转成带真实原因的 RuntimeError
            self._last_error = message
        self._emit(message, "success" if success else "error")

    def package_data(self):
        self._emit("Packaging data...")
        old = os.getcwd()
        try:
            os.chdir(self._working_dir)
            result = super().package_data()
            self._emit("Data packaging complete")
            return result
        finally:
            os.chdir(old)

    def connect_ssh(self):
        self._emit("Connecting to remote server...")
        old = os.getcwd()
        try:
            os.chdir(self._working_dir)
            super().connect_ssh(self._ssh_credentials)
            self._emit("SSH connection established")
            # 连接成功后先校验/纠正远程 python 路径，后续 setup_remote_workspace
            # 与 run_remote_training 会自动用到纠正后的值
            self._ensure_remote_python()
        finally:
            os.chdir(old)

    def _ensure_remote_python(self):
        """自动校验并纠正远程 python 路径（只改内存配置，不写 conf 文件）。

        配置/历史记录里的 python_path 可能是错的（默认值或他机路径），直接拿
        错误路径训练会在远程报 no such file or directory。这里复用 mypc_probe
        的发现逻辑，找一个能 import donkeycar 的解释器；任何失败都只记
        warning，绝不影响训练主流程。
        """
        # 局部导入，避免模块级循环依赖
        from mypc_probe import find_donkeycar_python

        self._emit("正在定位远程 Python 环境（可能需数十秒）...")
        configured = (self.get_config_value("python_path") or "").strip()
        try:
            found = find_donkeycar_python(self.ssh_client, configured)
        except Exception as e:  # noqa: BLE001 - 自动探测失败不得中断训练
            self._emit(f"Remote python auto-detection failed: {e}", level="warning")
            return
        if not found:
            self._emit("未在远程找到带 donkeycar 的 Python，将使用配置路径继续尝试",
                       level="warning")
            return
        # found 是 sys.executable（~ 已展开），需与配置值的展开结果比较
        try:
            resolved = self._resolve_remote_path(configured) if configured else ""
        except Exception:  # noqa: BLE001 - 展开失败不影响纠正
            resolved = ""
        if found == configured or found == resolved:
            return
        self.config["Remote"]["python_path"] = found
        self._emit(f"已自动修正远程 Python 路径: {found}")

    def setup_remote_workspace(self):
        self._emit("Setting up remote workspace...")
        old = os.getcwd()
        try:
            os.chdir(self._working_dir)
            path = super().setup_remote_workspace()
            self._emit(f"Remote workspace: {path}")
            return path
        finally:
            os.chdir(old)

    def upload_data(self, local_path, remote_filename):
        self._emit(f"Uploading data: {remote_filename} ...")
        old = os.getcwd()
        try:
            os.chdir(self._working_dir)
            result = super().upload_data(local_path, remote_filename)
            self._emit("Upload complete")
            return result
        finally:
            os.chdir(old)

    def download_model(self, model_name=None):
        self._emit("Downloading model...")
        old = os.getcwd()
        try:
            os.chdir(self._working_dir)
            result = super().download_model(model_name)
            self._emit("Model download complete")
            return result
        finally:
            os.chdir(old)

    # ------------------------------------------------------------------
    # Core override - replace Rich progress with queue streaming
    # ------------------------------------------------------------------
    def run_remote_training(self, remote_tar_path, model_name=None):
        remote_dir = self.remote_work_dir
        if not remote_dir:
            raise RuntimeError("Remote workspace not initialized. Please upload data first.")

        if model_name is None:
            model_name = self.get_config_value("model_name")

        # 记录续训会话：训练被中断后，「继续训练」可从上次最佳权重接着练
        save_session(self._working_dir, self.config_file, {
            "remote_work_dir": remote_dir,
            "model_name": model_name,
            "tub": self.data_dir,
            "host": (self._ssh_credentials or {}).get("host"),
        })

        python_path = self.get_config_value("python_path")
        python_path = self._resolve_remote_path(python_path)
        filename = os.path.basename(remote_tar_path)

        # 1. Pre-check Resources
        self._check_remote_resources(remote_dir)

        # 2. Extract
        self._emit("Extracting data on remote server...")
        cmd_extract = f"tar -xzf {remote_dir}/{filename} -C {remote_dir}"
        stdin, stdout, stderr = self.ssh_client.exec_command(cmd_extract)
        if stdout.channel.recv_exit_status() != 0:
            err = stderr.read().decode()
            raise RuntimeError(f"Remote extraction failed: {err}")
        self._emit("Extraction complete")

        # 3. Train
        self._emit(f"Starting remote training (Python: {python_path})...")
        model_type = self.get_config_value("model_type") or "linear"
        cmd_train = f"cd {remote_dir} && {python_path} train.py --tub ./data --model ./models/{model_name} --type {model_type}"
        if self._abort_requested:
            raise RuntimeError("训练已被用户停止")
        self._stream_remote_training(cmd_train)

    def _stream_remote_training(self, cmd):
        """执行远程训练命令并流式解析输出（进度解析、日志过滤、超时与完成标记）。"""
        # 重置进度状态，供 _parse_training_output_web 使用
        self.current_epoch = 0
        self.total_epochs = 0

        stdin, stdout, stderr = self.ssh_client.exec_command(cmd, get_pty=True)

        start_time = time.time()
        training_finished = False
        timeout = 3600  # 1 hour

        stdout_buffer = ""
        stderr_buffer = ""

        # TF noise keywords (same as parent)
        tf_noise_keywords = [
            "Unsupported signature for serialization",
            "tensorflow.python.framework.func_graph",
            "INFO:tensorflow:",
            "oneDNN custom operations are on",
            "Could not find cuda drivers",
            "Unable to register cuDNN factory",
            "Unable to register cuFFT factory",
            "Unable to register cuBLAS factory",
            "This TensorFlow binary is optimized",
            "TF-TRT Warning: Could not find TensorRT",
            "Created TensorFlow Lite delegate",
            "could not open file to read NUMA node",
            "Cannot dlopen some GPU libraries",
            "Skipping registering GPU devices",
            "TfLiteFlexDelegate delegate",
            "Created TensorFlow Lite XNNPACK delegate",
            "To enable the following instructions",
            "Your kernel may have been built without NUMA support",
            "tensorflow/core/util/port.cc",
            "external/local_tsl/tsl/cuda/cudart_stub.cc",
            "external/local_xla/xla/stream_executor/cuda"
        ]

        while not stdout.channel.exit_status_ready():
            if time.time() - start_time > timeout:
                raise TimeoutError("Training timeout (> 60 minutes)")

            # Process stdout
            if stdout.channel.recv_ready():
                chunk = stdout.channel.recv(1024).decode('utf-8', errors='ignore')
                stdout_buffer += chunk
                while True:
                    match = re.search(r'(\r|\n)', stdout_buffer)
                    if match:
                        line = stdout_buffer[:match.start()]
                        stdout_buffer = stdout_buffer[match.end():]
                        clean_line = _clean_line(line)
                        if not clean_line:
                            continue

                        self._parse_training_output_web(clean_line)

                        if "Finished training" in clean_line:
                            training_finished = True

                        is_progress_bar = _is_progress_bar_line(clean_line)
                        is_tf_noise = any(kw in clean_line for kw in tf_noise_keywords)

                        if not is_progress_bar and not is_tf_noise:
                            self._emit(clean_line)
                    else:
                        break

            # Process stderr
            if stderr.channel.recv_ready():
                chunk = stderr.channel.recv(1024).decode('utf-8', errors='ignore')
                stderr_buffer += chunk
                while '\n' in stderr_buffer:
                    line, stderr_buffer = stderr_buffer.split('\n', 1)
                    clean_line = _clean_line(line)
                    if clean_line:
                        is_progress_bar = _is_progress_bar_line(clean_line)
                        is_tf_noise = any(kw in clean_line for kw in tf_noise_keywords)
                        if not is_progress_bar and not is_tf_noise:
                            self._emit(clean_line, level="error")

            time.sleep(0.1)

        # Check remaining buffer
        remaining_stdout = _clean_line(stdout_buffer)
        if remaining_stdout:
            self._emit(remaining_stdout)
            if "Finished training" in remaining_stdout:
                training_finished = True
        remaining_stderr = _clean_line(stderr_buffer)
        if remaining_stderr:
            self._emit(remaining_stderr, level="error")

        end_time = time.time()
        duration = end_time - start_time
        minutes = int(duration // 60)
        seconds = int(duration % 60)

        if training_finished:
            self._emit(f"Training finished in {minutes}m {seconds}s")
        else:
            self._emit("Training finished without success message", level="warning")
            raise RuntimeError("Remote training ended without success marker ('Finished training') — check the log lines above for the remote error")

    def _parse_training_output_web(self, line):
        """Parse Keras output and emit progress events."""
        try:
            line = _clean_line(line)
            if not line:
                return

            epoch_match = re.search(r"Epoch (\d+)/(\d+)", line)
            if epoch_match:
                self.current_epoch = int(epoch_match.group(1))
                self.total_epochs = int(epoch_match.group(2))
                self._emit(f"Epoch {self.current_epoch}/{self.total_epochs}")
                return

            current_step = None
            total_steps = None
            # 兼容 Keras 2 的 [====>...] 与 Keras 3 的 ━━━ Unicode 粗线进度条
            step_match = re.match(r"^\s*(\d+)/(\d+)\s+[\[━]", line)
            if step_match:
                current_step = int(step_match.group(1))
                total_steps = int(step_match.group(2))

            # Progress bars may contain multiple "loss:" keys;
            # the last one is the current value.
            loss = None
            for m in re.finditer(r"loss: ([\d.]+(?:e[+-]?\d+)?)", line):
                loss = float(m.group(1))

            if self.total_epochs > 0 and current_step is not None and total_steps is not None:
                completed_epochs_progress = (self.current_epoch - 1) / self.total_epochs
                current_epoch_progress = (current_step / total_steps) / self.total_epochs
                total_progress = (completed_epochs_progress + current_epoch_progress) * 100
                self._emit_progress(
                    percent=total_progress,
                    current_epoch=self.current_epoch,
                    total_epochs=self.total_epochs,
                    current_step=current_step,
                    total_steps=total_steps,
                    loss=loss,
                )
            elif loss is not None:
                # Emit loss-only update preserving last known step state
                self._emit_progress(
                    percent=0,  # unchanged if no step info
                    current_epoch=self.current_epoch,
                    total_epochs=self.total_epochs,
                    current_step=current_step or 0,
                    total_steps=total_steps or 0,
                    loss=loss,
                )
        except Exception:
            pass

    def run(self, no_interactive=True):
        old = os.getcwd()
        try:
            os.chdir(self._working_dir)
            try:
                return super().run(no_interactive=no_interactive)
            except SystemExit as e:
                # 父类 run() 失败时 sys.exit(1)，真实原因刚通过 _log(success=False)
                # 记进 _last_error；这里转成 RuntimeError，让上层拿到真实原因
                # 而不是笼统的 "exited abnormally (code 1)"
                if e.code:
                    reason = self._last_error or f"Training flow exited abnormally (code {e.code})"
                    prefix = "Process failed: "
                    if reason.startswith(prefix):
                        reason = reason[len(prefix):]
                    raise RuntimeError(reason) from e
                return None
        finally:
            os.chdir(old)

    def abort_remote(self):
        """用户点击「停止」：杀掉远程训练进程并断开 SSH。

        任何失败都不抛出（停止操作必须幂等）：
        - 训练进行中：显式 pkill 远程训练进程，再关闭连接（关闭 pty 会让
          远程 sshd 给前台进程组发 SIGHUP，双保险）；流式循环随连接断开退出。
        - 尚未开始训练（打包/上传中）：_abort_requested 标志让
          run_remote_training / run_resume 在执行训练命令前自行中止；
          正在进行的 sftp 上传随连接关闭而中断。
        """
        self._abort_requested = True
        client = self.ssh_client
        if not client:
            return
        try:
            client.exec_command(
                "pkill -f 'train.py --tub'; pkill -f '_dd_resume_train.py --tub'")
        except Exception:
            pass
        try:
            client.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Resume training (mypc 断点续训)
    # ------------------------------------------------------------------
    def run_resume(self, session):
        """断点续训：加载上次训练留下的最优权重，复用远程已上传的同一份数据接着练。

        epoch 计数重新从 1 开始（不是接着上次的 38/100），early stopping 照常。
        所有失败以带中文原因的 RuntimeError 抛出，绝不 sys.exit。
        """
        old = os.getcwd()
        try:
            os.chdir(self._working_dir)
            try:
                # connect_ssh 内部会顺带纠正远程 python 路径（_ensure_remote_python）
                self.connect_ssh()
                if self._abort_requested:
                    raise RuntimeError("训练已被用户停止")

                self.remote_work_dir = session["remote_work_dir"]
                remote_dir = self.remote_work_dir
                model_name = session["model_name"]

                # 远程训练目录与已上传的数据必须还在，否则无法续训
                stdin, stdout, stderr = self.ssh_client.exec_command(
                    f"[ -d {remote_dir} ] && [ -d {remote_dir}/data ]")
                if stdout.channel.recv_exit_status() != 0:
                    raise RuntimeError("远程训练目录已不存在，请使用「开始训练」重新训练")

                # 找上次训练留下的最优权重检查点（排除 .tflite/.png/_meta.json 训练产物）
                # 注意必须加 -d：检查点可能是 SavedModel 目录（如 models/<name>/），
                # 不带 -d 时 ls 会展开列出目录内容而不是目录本身
                stdin, stdout, stderr = self.ssh_client.exec_command(
                    f"ls -dt {remote_dir}/models/{model_name}*")
                checkpoint = None
                for line in stdout.read().decode().splitlines():
                    candidate = line.strip()
                    if not candidate or candidate.endswith(":"):
                        continue
                    if candidate.endswith(".tflite") or candidate.endswith(".png") \
                            or candidate.endswith("_meta.json"):
                        continue
                    checkpoint = candidate
                    break
                if not checkpoint:
                    raise RuntimeError("未找到上次训练留下的检查点，请使用「开始训练」重新训练")

                new_model = self._generate_unique_model_name(self.get_config_value("model_name"))

                # 上传续训脚本：远程 train.py 模板不支持 --transfer，
                # 用独立脚本调 donkeydrifter pipeline 的 train(..., transfer, ...)
                local_script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                            "remote_resume_train.py")
                self.sftp_client.put(local_script, f"{remote_dir}/_dd_resume_train.py")

                python_path = self._resolve_remote_path(self.get_config_value("python_path"))
                model_type = self.get_config_value("model_type") or "linear"
                cmd = (f"cd {remote_dir} && {python_path} _dd_resume_train.py "
                       f"--tub ./data --model ./models/{new_model} --type {model_type} "
                       f"--transfer {checkpoint}")
                self._emit(f"正在从上次的最佳权重继续训练（检查点: {os.path.basename(checkpoint)}）...")
                self._stream_remote_training(cmd)

                self.download_model(new_model)

                # 会话模型名更新为新模型，支持再次续训（链式续训）
                save_session(self._working_dir, self.config_file, {
                    "remote_work_dir": remote_dir,
                    "model_name": new_model,
                    "tub": session.get("tub"),
                    "host": session.get("host"),
                })
            except SystemExit as e:
                # 与 run() 同理：绝不让 SystemExit 漏进上层线程变成静默死亡
                if e.code:
                    reason = self._last_error or f"续训流程异常退出 (code {e.code})"
                    prefix = "Process failed: "
                    if reason.startswith(prefix):
                        reason = reason[len(prefix):]
                    raise RuntimeError(reason) from e
            finally:
                self.cleanup(None)
        finally:
            os.chdir(old)
