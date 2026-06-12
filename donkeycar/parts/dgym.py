import os
import time
import numpy as np
import gymnasium as gym
import gym_donkeycar  # noqa: F401  -- registers donkey envs with gymnasium

from donkeycar.config import Config


def is_exe(fpath):
    return os.path.isfile(fpath) and os.access(fpath, os.X_OK)


class DonkeyGymEnv(object):

    def __init__(self, sim_path, host="127.0.0.1", port=9091, headless=0, env_name="donkey-generated-track-v0", sync="asynchronous", conf={}, record_location=False, record_gyroaccel=False, record_velocity=False, record_lidar=False, delay=0):

        # 保存原始配置，以便运行时重连复用
        self._sim_path = sim_path
        self._host = host
        self._port = port
        self._headless = headless
        self._env_name = env_name
        self._sync = sync
        self._conf = dict(conf)
        self._record_location = record_location
        self._record_gyroaccel = record_gyroaccel
        self._record_velocity = record_velocity
        self._record_lidar = record_lidar
        self._delay_ms = delay

        # 监控 myconfig.py 的变化
        self._myconfig_path = os.path.join(os.getcwd(), 'myconfig.py')
        self._myconfig_mtime = 0
        if os.path.exists(self._myconfig_path):
            self._myconfig_mtime = os.path.getmtime(self._myconfig_path)

        # 空帧占位
        img_h = self._conf.get("img_h", 120)
        img_w = self._conf.get("img_w", 160)
        self._empty_frame = np.zeros((img_h, img_w, 3), dtype=np.uint8)

        # 初始化环境
        self._try_connect()

        self.action = [0.0, 0.0, 0.0]
        self.running = True
        self.info = {'pos': (0., 0., 0.),
                     'speed': 0,
                     'cte': 0,
                     'gyro': (0., 0., 0.),
                     'accel': (0., 0., 0.),
                     'vel': (0., 0., 0.),
                     'lidar': []}
        self.delay = float(delay) / 1000
        self.record_location = record_location
        self.record_gyroaccel = record_gyroaccel
        self.record_velocity = record_velocity
        self.record_lidar = record_lidar

        self.buffer = []

    def _try_connect(self):
        """尝试连接模拟器。成功则设置 self.env，失败则保持 None。"""
        if self._sim_path != "remote":
            if not os.path.exists(self._sim_path):
                print(f"[DonkeyGymEnv] 模拟器路径不存在: {self._sim_path}")
                self.env = None
                self.frame = self._empty_frame.copy()
                self.connected = False
                return

            if not is_exe(self._sim_path):
                print(f"[DonkeyGymEnv] 模拟器路径不是可执行文件: {self._sim_path}")
                self.env = None
                self.frame = self._empty_frame.copy()
                self.connected = False
                return

        conf = dict(self._conf)
        conf["exe_path"] = self._sim_path
        conf["host"] = self._host
        conf["port"] = self._port
        conf["guid"] = 0
        conf["frame_skip"] = 1

        try:
            self.env = gym.make(self._env_name, conf=conf)
            self.frame, _ = self.env.reset()
            self.connected = True
            print(f"[DonkeyGymEnv] 已连接到模拟器 {self._host}:{self._port}")
        except Exception as e:
            self.env = None
            self.frame = self._empty_frame.copy()
            self.connected = False
            print(f"[DonkeyGymEnv] 无法连接到模拟器 ({self._host}:{self._port}): {e}")
            print("[DonkeyGymEnv] 将在后台持续尝试重连。请启动 DonkeySim 或通过 Web UI 配置正确的 SIM_HOST。")

    def _check_config_reload(self):
        """检查 myconfig.py 是否被修改，如果是则重新加载 SIM_HOST 等配置。"""
        if not os.path.exists(self._myconfig_path):
            return False

        current_mtime = os.path.getmtime(self._myconfig_path)
        if current_mtime <= self._myconfig_mtime:
            return False

        self._myconfig_mtime = current_mtime

        try:
            cfg = Config()
            cfg.from_pyfile(self._myconfig_path)

            changed = False

            # 检查 SIM_HOST 变化
            new_host = getattr(cfg, 'SIM_HOST', self._host)
            if isinstance(new_host, str) and new_host != self._host:
                print(f"[DonkeyGymEnv] 检测到 SIM_HOST 变化: {self._host} -> {new_host}")
                self._host = new_host
                changed = True

            # 检查 SIM_ARTIFICIAL_LATENCY 变化
            new_delay = getattr(cfg, 'SIM_ARTIFICIAL_LATENCY', self._delay_ms)
            if isinstance(new_delay, (int, float)) and new_delay != self._delay_ms:
                print(f"[DonkeyGymEnv] 检测到 SIM_ARTIFICIAL_LATENCY 变化: {self._delay_ms} -> {new_delay}")
                self._delay_ms = new_delay
                self.delay = float(new_delay) / 1000
                changed = True

            # 检查 DONKEY_GYM 开关
            new_gym = getattr(cfg, 'DONKEY_GYM', True)
            if not new_gym and self.env is not None:
                print("[DonkeyGymEnv] DONKEY_GYM 已关闭，断开模拟器连接")
                self._close_env()
                changed = True

            return changed
        except Exception as e:
            print(f"[DonkeyGymEnv] 重新加载配置失败: {e}")
            return False

    def _close_env(self):
        """安全关闭当前模拟器环境。"""
        if self.env is not None:
            try:
                self.env.close()
            except Exception:
                pass
            self.env = None
            self.frame = self._empty_frame.copy()
            self.connected = False

    def delay_buffer(self, frame, info):
        now = time.time()
        buffer_tuple = (now, frame, info)
        self.buffer.append(buffer_tuple)

        # go through the buffer
        num_to_remove = 0
        for buf in self.buffer:
            if now - buf[0] >= self.delay:
                num_to_remove += 1
                self.frame = buf[1]
            else:
                break

        # clear the buffer
        del self.buffer[:num_to_remove]

    def _is_env_connected(self):
        """检查底层模拟器 TCP 连接是否仍然有效。"""
        if self.env is None:
            return False
        try:
            client = getattr(self.env, "viewer", None)
            if client is not None:
                client = getattr(client, "client", None)
            if client is not None and hasattr(client, "is_connected"):
                return client.is_connected()
        except Exception:
            pass
        return True

    def _request_reconnect(self):
        """标记需要在下一次 update 循环中强制重建模拟器连接。"""
        if self.env is not None:
            print("[DonkeyGymEnv] 收到强制重连请求，准备重建模拟器连接")
            self._close_env()

    def update(self):
        while self.running:
            # 如果未连接，检查配置是否有更新并尝试重连
            if self.env is None:
                self._check_config_reload()
                self._try_connect()
                if self.env is None:
                    time.sleep(1.0)
                    continue

            # 健康检查：如果底层连接已断开，主动关闭环境等待重连
            if not self._is_env_connected():
                print("[DonkeyGymEnv] 检测到模拟器连接已断开，准备重连")
                self._close_env()
                time.sleep(1.0)
                continue

            try:
                if self.delay > 0.0:
                    step_result = self.env.step(self.action)
                    current_frame, _, _, _, current_info = step_result
                    self.delay_buffer(current_frame, current_info)
                else:
                    step_result = self.env.step(self.action)
                    self.frame, _, _, _, self.info = step_result
            except Exception as e:
                print(f"[DonkeyGymEnv] 模拟器连接异常: {e}")
                self._close_env()
                time.sleep(1.0)

    def run_threaded(self, steering, throttle, brake=None, reconnect=False):
        if reconnect:
            self._request_reconnect()

        if steering is None or throttle is None:
            steering = 0.0
            throttle = 0.0
        if brake is None:
            brake = 0.0

        self.action = [steering, throttle, brake]

        # Output Sim-car position information if configured
        outputs = [self.frame]
        if self.record_location:
            outputs += self.info['pos'][0],  self.info['pos'][1],  self.info['pos'][2],  self.info['speed'], self.info['cte']
        if self.record_gyroaccel:
            outputs += self.info['gyro'][0], self.info['gyro'][1], self.info['gyro'][2], self.info['accel'][0], self.info['accel'][1], self.info['accel'][2]
        if self.record_velocity:
            outputs += self.info['vel'][0],  self.info['vel'][1],  self.info['vel'][2]
        if self.record_lidar:
            outputs += [self.info['lidar']]
        if len(outputs) == 1:
            return self.frame
        else:
            return outputs

    def shutdown(self):
        self.running = False
        time.sleep(0.2)
        self._close_env()
