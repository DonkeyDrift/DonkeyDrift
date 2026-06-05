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


# Regex to strip ANSI escape codes (colour, cursor movement, etc.)
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


def _clean_line(raw: str) -> str:
    """Remove ANSI escape codes and surrounding whitespace."""
    return _ANSI_RE.sub('', raw).strip()


class WebOnlineTrainer(OnlineTrainer):
    """OnlineTrainer subclass that streams output to a queue instead of Rich console."""

    def __init__(self, config_file="train_online.conf",
                 log_queue: Optional[queue.Queue] = None,
                 working_dir: Optional[str] = None):
        self._log_queue = log_queue
        self._working_dir = working_dir or os.getcwd()
        # Ensure CWD-sensitive operations use the correct directory
        old_cwd = os.getcwd()
        try:
            os.chdir(self._working_dir)
            super().__init__(config_file)
        finally:
            os.chdir(old_cwd)

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
            super().connect_ssh()
            self._emit("SSH connection established")
        finally:
            os.chdir(old)

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
        cmd_train = f"cd {remote_dir} && {python_path} train.py --tub ./data --model ./models/{model_name} --type linear"
        stdin, stdout, stderr = self.ssh_client.exec_command(cmd_train, get_pty=True)

        start_time = time.time()
        training_finished = False
        timeout = 3600  # 1 hour

        stdout_buffer = ""
        stderr_buffer = ""

        # State for progress parsing
        self.current_epoch = 0
        self.total_epochs = 0

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

                        is_progress_bar = "ETA:" in clean_line or ("[" in clean_line and "]" in clean_line and "=" in clean_line)
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
                        is_progress_bar = "ETA:" in clean_line or ("[" in clean_line and "]" in clean_line and "=" in clean_line)
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
            step_match = re.match(r"^\s*(\d+)/(\d+)\s+\[", line)
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
            return super().run(no_interactive=no_interactive)
        finally:
            os.chdir(old)
