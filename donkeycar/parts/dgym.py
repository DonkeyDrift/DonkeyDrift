import os
import time
import threading
import numpy as np
import gymnasium as gym
import gym_donkeycar  # noqa: F401  -- registers donkey envs with gymnasium

from donkeycar.config import Config

from .frame_freshness import set_source_arrival

try:
    import cv2
except Exception:  # pragma: no cover - 缺少 OpenCV 时预览下采样退化为原样返回
    cv2 = None


def is_exe(fpath):
    return os.path.isfile(fpath) and os.access(fpath, os.X_OK)


class DonkeyGymEnv(object):

    def __init__(self, sim_path, host="127.0.0.1", port=9091, headless=0, env_name="donkey-generated-track-v0", sync="asynchronous", conf={}, record_location=False, record_gyroaccel=False, record_velocity=False, record_lidar=False, delay=0, output_preview=False):

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
        self._img_h = int(self._conf.get("img_h", 120))
        self._img_w = int(self._conf.get("img_w", 160))
        # 模拟器渲染分辨率与 NN 输入分辨率解耦：未显式设置 render_img_w/render_img_h 时
        # 默认按 640×480 渲染——与预览编码分辨率上限（DriveApiBridge
        # DRIVE_WEBRTC_PREVIEW_MAX_*，默认 640×480）对齐。实测模拟器遥测/出图节拍
        # 固定 20fps、与渲染分辨率无关，更高的渲染分辨率不增加任何帧率或预览画质，
        # 只会多烧模拟器 CPU、放大每帧 JPEG 编解码与 socket 传输耗时（真实体感时延）。
        # 显式设置 render_img_w/render_img_h 可覆盖该默认值；
        # NN 输入（cam/image_array）始终为 img_w×img_h（在 dgym 内下采样）。
        self._render_img_h = int(self._conf.get("render_img_h") or 480)
        self._render_img_w = int(self._conf.get("render_img_w") or 640)
        self._output_preview = bool(output_preview)
        self._empty_frame = np.zeros((self._img_h, self._img_w, 3), dtype=np.uint8)
        self._empty_preview_frame = np.zeros((self._render_img_h, self._render_img_w, 3), dtype=np.uint8)
        self.frame = self._empty_frame.copy()
        self.preview_frame = self._empty_preview_frame.copy()

        # 看门狗：记录最近一次 env.step() 成功返回的时间戳。底层 gym_donkeycar 的
        # observe() 在模拟器断连后会无限自旋（无超时），update() 线程会被卡死在
        # step() 内部。主循环侧 run_threaded() 据此检测「长时间无新帧」并强制重连，
        # 不依赖 gym_donkeycar 内部状态。
        self._watchdog_sec = float(self._conf.get("watchdog_sec", 5.0))
        self._last_frame_ts = time.time()

        # 重连互斥锁：update() 线程与主循环侧（run_threaded 的强制重连/看门狗）
        # 都可能触发重建，避免两个线程各建一个 env 互相踩踏
        self._reconnect_lock = threading.Lock()

        # 强制重连合并窗口：后端重连命令基于滞后遥测盲发，距上次重建完成
        # 不足此窗口且连接健康时视为陈旧请求合并掉（0=从未重建过）
        self._last_rebuild_done_ts = 0.0
        self._coalesce_sec = float(self._conf.get("reconnect_coalesce_sec", 2.0))

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
                self.preview_frame = self._empty_preview_frame.copy()
                self.connected = False
                return

            if not is_exe(self._sim_path):
                print(f"[DonkeyGymEnv] 模拟器路径不是可执行文件: {self._sim_path}")
                self.env = None
                self.frame = self._empty_frame.copy()
                self.preview_frame = self._empty_preview_frame.copy()
                self.connected = False
                return

        conf = dict(self._conf)
        conf["exe_path"] = self._sim_path
        conf["host"] = self._host
        conf["port"] = self._port
        conf["guid"] = 0
        conf["frame_skip"] = 1
        # 渲染分辨率与 NN 输入解耦：渲染分辨率（缺省 1920×1080 全高清）与 NN 输入
        # 不一致时，覆盖发给模拟器的 img_w/img_h 与 cam_resolution，
        # 让模拟器按渲染分辨率出图（NN 输入帧在 _set_frame 内下采样回 img_w×img_h）。
        if (self._render_img_w, self._render_img_h) != (self._img_w, self._img_h):
            conf["img_w"] = self._render_img_w
            conf["img_h"] = self._render_img_h
            conf["cam_resolution"] = (self._render_img_h, self._render_img_w, 3)

        try:
            self.env = gym.make(self._env_name, conf=conf)
            raw_frame, _ = self.env.reset()
            self._set_frame(raw_frame)
            self.connected = True
            self._last_frame_ts = time.time()
            print(f"[DonkeyGymEnv] 已连接到模拟器 {self._host}:{self._port}"
                  f"（cam/image_array {self._img_w}x{self._img_h}，"
                  f"渲染 {self._render_img_w}x{self._render_img_h}）")
        except Exception as e:
            self.env = None
            self.frame = self._empty_frame.copy()
            self.preview_frame = self._empty_preview_frame.copy()
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
            self.preview_frame = self._empty_preview_frame.copy()
            self.connected = False

    def _set_frame(self, raw_frame):
        """把模拟器返回的原始渲染帧拆分为 NN 输入帧与预览帧。

        模拟器按渲染分辨率（render_img_w×render_img_h）出图；NN 输入
        （cam/image_array）需要 IMAGE_W×IMAGE_H（img_w×img_h），故在渲染
        分辨率更高时下采样；预览帧（preview/image_array）保留渲染分辨率
        原始帧，供 Drive 页面展示最高画质。
        """
        if raw_frame is None:
            return
        # 帧到达时刻入侧信道：帧缓冲以它为时间戳并按它去重，让
        # 「出帧→车辆循环轮询」等待计入时延口径、重复轮询不虚增帧率。
        set_source_arrival()
        h, w = raw_frame.shape[:2]
        if h == self._img_h and w == self._img_w:
            self.frame = raw_frame
            self.preview_frame = raw_frame
            return
        self.preview_frame = raw_frame
        if cv2 is not None:
            try:
                self.frame = cv2.resize(raw_frame, (self._img_w, self._img_h))
            except Exception:
                self.frame = raw_frame
        else:
            self.frame = raw_frame

    def delay_buffer(self, frame, info):
        now = time.time()
        buffer_tuple = (now, frame, info)
        self.buffer.append(buffer_tuple)

        # go through the buffer
        num_to_remove = 0
        for buf in self.buffer:
            if now - buf[0] >= self.delay:
                num_to_remove += 1
                self._set_frame(buf[1])
            else:
                break

        # clear the buffer
        del self.buffer[:num_to_remove]

    def _raw_env(self):
        """取到最底层真实 env。

        gym.make 返回的是 gymnasium wrapper（如 OrderEnforcing），它不代理
        任意属性——`getattr(wrapper, "viewer")` 永远拿不到 DonkeyEnv 的
        viewer，只有 `wrapper.unwrapped` 才能到底。健康检查/遥测时间戳若
        看不见 viewer，会「保守按有效」永远放行：RST 后 update() 线程以
        陈旧帧全速空转（100% CPU），车端僵尸运行、遥测谎报 sim_connected。
        """
        env = self.env
        if env is None:
            return None
        try:
            if isinstance(env, gym.Wrapper):
                return env.unwrapped
        except Exception:
            pass
        return env

    def _env_client(self):
        """取到底层 SDClient（须穿透 gymnasium wrapper，见 _raw_env）。"""
        raw = self._raw_env()
        if raw is None:
            return None
        try:
            viewer = getattr(raw, "viewer", None)
            return getattr(viewer, "client", None)
        except Exception:
            return None

    def _is_env_connected(self):
        """检查底层模拟器 TCP 连接是否仍然有效。"""
        if self.env is None:
            return False
        client = self._env_client()
        if client is not None:
            is_conn = getattr(client, "is_connected", None)
            if callable(is_conn):
                try:
                    return bool(is_conn())
                except Exception:
                    return False
            # 老客户端没有 is_connected 时的兜底信号
            if getattr(client, "aborted", False):
                return False
            return bool(getattr(client, "do_process_msgs", True))
        # 拿不到 client（库结构变化）：退而用遥测时间戳——连接死了遥测必停。
        # 之前无条件「保守按有效」放行，wrapper 挡住 viewer 后健康检查永久
        # 失明，RST 僵尸态就这么来的。
        ts = self._telemetry_ts()
        if ts is not None:
            return (time.time() - ts) <= self._watchdog_sec
        return True

    def _telemetry_ts(self):
        """底层最近一次收到模拟器遥测的时间戳；取不到返回 None。

        比帧时间戳更权威：observe() 在断连后会返回陈旧帧，帧时间戳照样
        前进，只有遥测时间戳能暴露「连接活着但画面已死」。
        """
        try:
            raw = self._raw_env()
            handler = getattr(getattr(raw, "viewer", None), "handler", None)
            ts = getattr(handler, "time_received", None)
            if isinstance(ts, (int, float)):
                return float(ts)
        except Exception:
            pass
        return None

    def _telemetry_is_fresh(self):
        """最近一次遥测/帧是否在看门狗窗口内（连接尚算活着）。"""
        ts = self._telemetry_ts() or self._last_frame_ts
        return (time.time() - ts) <= self._watchdog_sec

    def _rebuild_connection(self, only_if_stale=False, coalesce=False):
        """同步重建模拟器连接：关旧 env 后立刻重连。

        必须在主循环侧（run_threaded）同步执行：模拟器断连后 update()
        线程往往卡死在 observe() 的无限自旋里，永远不会回到 update()
        循环顶部执行重连——只关不断会让车端永久掉线。锁保证与 update()
        线程的重连路径互斥，不产生双 env。

        only_if_stale=True（看门狗路径）：持锁后双检遥测新鲜度，别的路径
        刚重建完就跳过，避免把健康的新连接毫无意义地关掉再建。

        coalesce=True（强制重连路径）：仅当下列条件同时成立才跳过——
        连接此刻健康 且 距上次重建完成不足 coalesce 窗口。后端的重连
        命令基于滞后遥测盲发，若它生成于上一次重建完成之前/期间，重建
        已经代劳，再拆再建就是实测过的「重建风暴」：把刚建好的 env 又
        关一次，模拟器侧多一次 load_scene。其余情形一律真重建（契约：
        重连命令必须真重建）。
        """
        with self._reconnect_lock:
            if only_if_stale and self._telemetry_is_fresh():
                print("[DonkeyGymEnv] 连接仍健康（遥测新鲜），跳过本次重建")
                return self.env is not None
            if (coalesce and self._telemetry_is_fresh()
                    and time.time() - self._last_rebuild_done_ts
                    <= self._coalesce_sec):
                print("[DonkeyGymEnv] 刚重建过且连接健康，合并本次重连请求")
                return self.env is not None
            self._close_env()
            # 重建前重载配置：连接器改写 SIM_HOST 后无需重启驾驶，
            # 下一次重连（看门狗/强制重连/后台恢复）自动用新地址
            self._check_config_reload()
            self._try_connect()
            self._last_rebuild_done_ts = time.time()
            return self.env is not None

    def _request_reconnect(self):
        """强制重建模拟器连接（Web UI reconnect_simulator 命令的入口）。

        env 已为 None（此前重连失败）时也要尝试：update() 线程可能已
        卡死，主循环是唯一还活着能重连的执行流。

        coalesce=True 只合并「陈旧请求」：后端基于滞后遥测盲发的重连
        命令，其生成时刻早于上一次重建的完成时刻（含重建进行中才送达
        的情形）——那次重建已经代劳，再拆再建就是实测过的重建风暴，
        而且模拟器侧每条新连接都会多一次 load_scene。其余情形一律真重建。
        """
        print("[DonkeyGymEnv] 收到强制重连请求，重建模拟器连接")
        self._rebuild_connection(coalesce=True)

    def update(self):
        while self.running:
            # 如果未连接，检查配置是否有更新并尝试重连
            if self.env is None:
                # 双检锁：主循环侧可能已在本线程等待期间完成重建
                with self._reconnect_lock:
                    if self.env is None:
                        self._check_config_reload()
                        self._try_connect()
                if self.env is None:
                    time.sleep(1.0)
                    continue

            # 健康检查：如果底层连接已断开，主动关闭环境等待重连
            checked_env = self.env
            if not self._is_env_connected():
                print("[DonkeyGymEnv] 检测到模拟器连接已断开，准备重连")
                with self._reconnect_lock:
                    # 采样到断开的间隙里主循环可能已重建出新 env：
                    # 只关刚才判定断开的那个，别误杀替换后的新连接
                    if self.env is checked_env:
                        self._close_env()
                time.sleep(1.0)
                continue
            # 本轮要驱动的 env 固定为当前对象：主循环侧重建期间 self.env
            # 可能已被替换成新 env，旧 env 的 step 异常不应把新 env 误关掉
            env = self.env
            try:
                if self.delay > 0.0:
                    step_result = env.step(self.action)
                    current_frame, _, _, _, current_info = step_result
                    self.delay_buffer(current_frame, current_info)
                else:
                    step_result = env.step(self.action)
                    current_frame, _, _, _, current_info = step_result
                    self._set_frame(current_frame)
                    self.info = current_info
                if self.env is env:
                    self._last_frame_ts = time.time()
            except Exception as e:
                print(f"[DonkeyGymEnv] 模拟器连接异常: {e}")
                if self.env is env:
                    self._close_env()
                time.sleep(1.0)

    def run_threaded(self, steering, throttle, brake=None, reconnect=False):
        if reconnect:
            self._request_reconnect()

        if self.env is not None:
            # 保持 connected 与真实 TCP 健康一致：SimConnectionState（遥测
            # sim_connected）取的就是它，连接死后必须及时翻假，否则后端的
            # 恢复门控会被假 True 挡住、永远不发重连命令
            self.connected = self._is_env_connected()

        # 看门狗：出现「遥测停止」即重建连接——覆盖三种死法：
        # a) TCP 被对端复位（update 侧健康检查也会重建，双保险）；
        # b) 连接活着但模拟器哑巴（observe 自旋/陈旧帧，帧时间戳会假前进，
        #    所以以遥测时间戳为准）；
        # c) update 线程已彻底卡死/死亡（连健康检查都没人跑）。
        # 只 _close_env 不够：必须主循环同步「关闭+重连」，否则车端永久掉线。
        if self.env is not None and not self._telemetry_is_fresh():
            print(f"[DonkeyGymEnv] 看门狗：超过 {self._watchdog_sec:.1f}s 无新遥测，重建连接")
            # only_if_stale：持锁双检，避免和 update 侧的重建赛跑后
            # 把刚建好的健康连接再拆一遍
            self._rebuild_connection(only_if_stale=True)

        if steering is None or throttle is None:
            steering = 0.0
            throttle = 0.0
        if brake is None:
            brake = 0.0

        self.action = [steering, throttle, brake]

        # Output Sim-car position information if configured
        outputs = [self.frame]
        if self._output_preview:
            outputs.append(self.preview_frame)
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
