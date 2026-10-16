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
        # 预览帧直推回调（如 DriveApiBridge.frame_buffer.update）：模拟器帧到达即推，
        # 不经过车辆主循环轮询。None = 保持轮询喂帧的旧行为。
        self._frame_sink = None

        # 看门狗：记录最近一次 env.step() 成功返回的时间戳。底层 gym_donkeycar 的
        # observe() 在模拟器断连后会无限自旋（无超时），update() 线程会被卡死在
        # step() 内部。主循环侧 run_threaded() 据此检测「长时间无新帧」并强制重连，
        # 不依赖 gym_donkeycar 内部状态。
        self._watchdog_sec = float(self._conf.get("watchdog_sec", 5.0))
        self._last_frame_ts = time.time()

        # 重连互斥锁：update() 线程与重建线程（后台 worker/看门狗请求）
        # 都可能触发重建，避免两个线程各建一个 env 互相踩踏
        self._reconnect_lock = threading.Lock()

        # 重建请求通道：主循环侧（run_threaded）只投递请求，由专用线程执行。
        # close+gym.make+reset 要数秒（模拟器 load_scene），在主循环同步执行会
        # 卡住 60Hz 车辆循环、转向/油门断供；worker 化后主循环零阻塞，重建期间
        # 遥测继续（sim_connected=False 如实上报）、控制消息照常消费。
        self._rebuild_cond = threading.Condition()
        self._rebuild_mode = None  # None | 'force'（重连命令）| 'watchdog'（看门狗）
        self._rebuild_thread = threading.Thread(
            target=self._rebuild_worker, name='dgym-reconnect', daemon=True)

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

        self._rebuild_thread.start()

    def _rebuild_worker(self):
        """重建线程：串行消费主循环投递的重建请求，直到进程退出。

        语义（coalesce 合并、only_if_stale 双检新鲜度）在执行时刻评估，
        挂起期间的重复请求已被 _post_rebuild 合并。
        """
        while True:
            with self._rebuild_cond:
                while self.running and self._rebuild_mode is None:
                    self._rebuild_cond.wait(timeout=0.5)
                if not self.running:
                    return
                mode = self._rebuild_mode
                self._rebuild_mode = None
            try:
                self._rebuild_connection(
                    coalesce=(mode == 'force'),
                    only_if_stale=(mode == 'watchdog'))
            except Exception as e:
                print(f"[DonkeyGymEnv] 后台重建模拟器连接异常: {e}")

    def _post_rebuild(self, mode):
        """向重建线程投递一次重建请求；挂起中的同类请求合并，force 升级 watchdog。"""
        with self._rebuild_cond:
            if self._rebuild_mode == 'force' or (
                    self._rebuild_mode == 'watchdog' and mode == 'watchdog'):
                return
            self._rebuild_mode = mode
            self._rebuild_cond.notify_all()

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

    def set_frame_sink(self, sink):
        """注册预览帧直推回调(如 DriveApiBridge.frame_buffer.update)。

        模拟器源是事件驱动推送(update 线程在 env.step 返回时即拿到新帧),而
        WebRTC 帧缓冲此前只能等车辆主循环轮询 run_threaded 喂帧——车辆循环
        负载一高(推理/录制)实际节拍跌破源帧率时,预览帧被欠采样(实测 58Hz
        源经 60Hz 轮询只采样到 ~50Hz 进编码器)。直推后帧路径不再经过车辆循环,
        编码器吃满真实源帧率,「出帧→被拾取」的轮询等待也归零。
        实车路径(侧信道恒 None)不受帧率影响,但同样的欠采样逻辑适用,故接线
        由模板按 video_transport 决定,本方法本身与传输方式无关。
        """
        self._frame_sink = sink

    def _push_frame_sink(self):
        # getattr 兜底:单测可能绕过 __init__ 构造实例
        sink = getattr(self, "_frame_sink", None)
        if sink is not None:
            try:
                self._sink_pushes = getattr(self, "_sink_pushes", 0) + 1
                sink(self.preview_frame)
            except Exception as e:
                # 喂帧失败绝不能拖死模拟器采集线程;丢帧计数用于诊断
                self._sink_errors = getattr(self, "_sink_errors", 0) + 1
                if self._sink_errors % 50 == 1:
                    print(f"[DonkeyGymEnv] frame sink 异常 #{self._sink_errors}: {e!r}")

    def _set_frame(self, raw_frame):
        """把模拟器返回的原始渲染帧拆分为 NN 输入帧与预览帧。

        模拟器按渲染分辨率（render_img_w×render_img_h）出图；NN 输入
        （cam/image_array）需要 IMAGE_W×IMAGE_H（img_w×img_h），故在渲染
        分辨率更高时下采样；预览帧（preview/image_array）保留渲染分辨率
        原始帧，供 Drive 页面展示最高画质。
        """
        if raw_frame is None:
            return
        h, w = raw_frame.shape[:2]
        if h == self._img_h and w == self._img_w:
            self.frame = raw_frame
            self.preview_frame = raw_frame
            self._arrive_and_push()
            return
        self.preview_frame = raw_frame
        self._arrive_and_push()
        if cv2 is not None:
            try:
                self.frame = cv2.resize(raw_frame, (self._img_w, self._img_h))
            except Exception:
                self.frame = raw_frame
        else:
            self.frame = raw_frame

    def _arrive_and_push(self):
        """帧对象先落地、再记到达、后直推——三步顺序是正确性关键。

        车辆循环的 run_threaded 与采集线程并发读 preview_frame；若先把到达
        时刻写入侧信道再换 preview_frame，车辆循环可能在两操作之间读到
        「旧帧 + 新到达时刻」——帧缓冲按到达时刻去重时会吞掉紧随其后的真实
        新帧（实测 60Hz 源因此掉到 ~52Hz，且旧帧被盖上新时间戳污染时延口径）。
        先换帧对象再记时刻则要么读到「新帧+旧时刻」去重跳过（安全），要么
        整套一致，永远不会错杀真实新帧。
        """
        fid = id(self.preview_frame)
        if fid == getattr(self, "_last_frame_obj", None):
            self._dup_frame_objs = getattr(self, "_dup_frame_objs", 0) + 1
        self._last_frame_obj = fid
        set_source_arrival()
        self._push_frame_sink()

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

        由后台重建线程（_rebuild_worker）执行；update() 线程自身卡死在
        observe() 无限自旋里时它也照常工作，不会出现「只关不断、车端
        永久掉线」。锁保证与 update() 线程的重连路径互斥，不产生双 env。

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

        只向后台重建线程投递请求、立即返回：重建（close+load_scene）耗时
        数秒，同步执行会把车辆主循环卡住、转向/油门断供。env 已为 None
        （此前重连失败）时也要尝试：update() 线程可能已卡死，本路径是
        唯一还活着能重连的执行流。

        worker 内的 coalesce 只合并「陈旧请求」：后端基于滞后遥测盲发的
        重连命令，其生成时刻早于上一次重建的完成时刻（含重建进行中才送达
        的情形）——那次重建已经代劳，再拆再建就是实测过的重建风暴，
        而且模拟器侧每条新连接都会多一次 load_scene。其余情形一律真重建。
        """
        print("[DonkeyGymEnv] 收到强制重连请求，交由后台线程重建模拟器连接")
        self._post_rebuild('force')

    def request_reset_to_nearest(self):
        """就近复位模拟器小车（Web UI 复位按钮的模拟器侧入口）。

        发 sdsim 的 reset_to_nearest 消息：模拟器把该车瞬移到最近赛道
        中央并按赛道切线朝向摆正（与模拟器本地 R 键同一套逻辑）。经
        _env_client() 穿透 wrapper 拿到底层 SDClient 直发，不依赖
        gym_donkeycar 提供封装；旧版模拟器未注册该消息时仅打一行日志
        忽略，不报错、不影响驾驶。
        """
        client = self._env_client()
        send_now = getattr(client, "send_now", None)
        if not callable(send_now):
            print("[DonkeyGymEnv] 就近复位失败：底层模拟器客户端不可用")
            return
        try:
            send_now({"msg_type": "reset_to_nearest"})
            print("[DonkeyGymEnv] 已发送就近复位指令 (reset_to_nearest)")
        except Exception as e:
            print(f"[DonkeyGymEnv] 发送就近复位指令失败: {e}")

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
                    _t0 = time.perf_counter()
                    step_result = env.step(self.action)
                    _t1 = time.perf_counter()
                    current_frame, _, _, _, current_info = step_result
                    self._set_frame(current_frame)
                    _t2 = time.perf_counter()
                    self.info = current_info
                    # 采集循环诊断:step 等待+返回 vs 本帧处理的分段耗时
                    self._upd_step_s = getattr(self, "_upd_step_s", 0.0) + (_t1 - _t0)
                    self._upd_frame_s = getattr(self, "_upd_frame_s", 0.0) + (_t2 - _t1)
                    self._upd_n = getattr(self, "_upd_n", 0) + 1
                if self.env is env:
                    self._last_frame_ts = time.time()
            except Exception as e:
                print(f"[DonkeyGymEnv] 模拟器连接异常: {e}")
                if self.env is env:
                    self._close_env()
                time.sleep(1.0)

    def run_threaded(self, steering, throttle, brake=None, reconnect=False, reset_car=False):
        # 采集链路分段耗时诊断:DRIVE_DGYM_TIMING=1 时每 5s 把 gym 客户端
        # recv/parse/telemetry 累计耗时打到 drive 日志(排查源帧率问题用,默认关)。
        now_diag = time.time()
        if os.environ.get("DRIVE_DGYM_TIMING", "").strip() in ("1", "true", "yes") and \
                now_diag - getattr(self, "_last_timing_log", 0.0) >= 5.0:
            self._last_timing_log = now_diag
            try:
                from gym_donkeycar.core.client import TIMING
                n = max(TIMING.get("n", 0), 1)
                print(f"[dgym-timing] n={TIMING['n']} "
                      f"telemetry={TIMING['telemetry']/n*1000:.2f}ms/帧 "
                      f"parse={TIMING['parse']/n*1000:.2f}ms/帧 "
                      f"recv_xfer={TIMING['recv_xfer']/n*1000:.2f}ms/帧 "
                      f"recv_wait={TIMING['recv_wait']:.2f}s/5s | "
                      f"更新循环: n={getattr(self,'_upd_n',0)} "
                      f"step={getattr(self,'_upd_step_s',0)/max(getattr(self,'_upd_n',1),1)*1000:.2f}ms/iter "
                      f"set_frame={getattr(self,'_upd_frame_s',0)/max(getattr(self,'_upd_n',1),1)*1000:.2f}ms/iter "
                      f"sink_errors={getattr(self,'_sink_errors',0)} "
                      f"dup_frame_objs={getattr(self,'_dup_frame_objs',0)} "
                      f"sink_pushes={getattr(self,'_sink_pushes',0)}")
                for k in ("recv_wait", "recv_xfer", "parse", "telemetry", "n"):
                    TIMING[k] = 0.0
                self._upd_step_s = 0.0
                self._upd_frame_s = 0.0
                self._upd_n = 0
                self._sink_pushes = 0
                self._dup_frame_objs = 0
            except Exception:
                pass

        if reconnect:
            self._request_reconnect()

        if reset_car:
            self.request_reset_to_nearest()

        if self.env is not None:
            # 保持 connected 与真实 TCP 健康一致：SimConnectionState（遥测
            # sim_connected）取的就是它，连接死后必须及时翻假，否则后端的
            # 恢复门控会被假 True 挡住、永远不发重连命令
            self.connected = self._is_env_connected()

        # 看门狗：出现「遥测停止」即请求后台重建连接——覆盖三种死法：
        # a) TCP 被对端复位（update 侧健康检查也会重建，双保险）；
        # b) 连接活着但模拟器哑巴（observe 自旋/陈旧帧，帧时间戳会假前进，
        #    所以以遥测时间戳为准）；
        # c) update 线程已彻底卡死/死亡（连健康检查都没人跑）。
        # 重建由专用线程执行（含关闭+重连），主循环只投递请求不等待。
        if self.env is not None and not self._telemetry_is_fresh():
            print(f"[DonkeyGymEnv] 看门狗：超过 {self._watchdog_sec:.1f}s 无新遥测，请求后台重建连接")
            # worker 执行时 only_if_stale 双检，避免和 update 侧的重建赛跑后
            # 把刚建好的健康连接再拆一遍
            self._post_rebuild('watchdog')

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
        # 唤醒重建线程退出；有挂起请求也不执行（模拟器生命周期已结束）
        with self._rebuild_cond:
            self._rebuild_cond.notify_all()
        if self._rebuild_thread.is_alive():
            self._rebuild_thread.join(timeout=2.0)
        time.sleep(0.2)
        self._close_env()
