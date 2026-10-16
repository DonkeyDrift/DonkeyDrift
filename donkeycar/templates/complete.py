#!/usr/bin/env python3
"""
Scripts to drive a donkey 2 car

Usage:
    manage.py [drive] [--model=<model>] [--js] [--type=(linear|categorical)] [--camera=(single|stereo)] [--meta=<key:value> ...] [--myconfig=<filename>]
    manage.py train [--tubs=tubs] (--model=<model>) [--type=(linear|inferred|tensorrt_linear|tflite_linear)]

Options:
    -h --help               Show this screen.
    --js                    Use physical joystick.
    -f --file=<file>        A text file containing paths to tub files, one per line. Option may be used more than once.
    --meta=<key:value>      Key/Value strings describing describing a piece of meta data about this drive. Option may be used more than once.
    --myconfig=filename     Specify myconfig file to use. 
                            [default: myconfig.py]
"""
from docopt import docopt

#
# import cv2 early to avoid issue with importing after tensorflow
# see https://github.com/opencv/opencv/issues/14884#issuecomment-599852128
#
try:
    import cv2
except:
    pass


import sys
import os
import json
import donkeydrifter as dk
from donkeydrifter.parts.behavior import BehaviorPart
from donkeydrifter.parts.controller import JoystickController
from donkeydrifter.parts.datastore import TubHandler
from donkeydrifter.parts.drive_api_bridge import DriveApiBridge
from donkeydrifter.parts.pilot_holder import PilotHolder
from donkeydrifter.parts.explode import ExplodeDict
from donkeydrifter.parts.file_watcher import FileWatcher
from donkeydrifter.parts.kinematics import (Bicycle,
                                        BicycleUnnormalizeAngularVelocity,
                                        InverseBicycle, InverseUnicycle,
                                        NormalizeSteeringAngle,
                                        TwoWheelSteeringThrottle, Unicycle,
                                        UnicycleUnnormalizeAngularVelocity,
                                        UnnormalizeSteeringAngle)
from donkeydrifter.parts.launch import AiLaunch
from donkeydrifter.parts.pipe import Pipe
from donkeydrifter.parts.throttle_filter import ThrottleFilter
from donkeydrifter.parts.steering_smoother import EmaSmoother, SteeringSmoother
from donkeydrifter.parts.transform import DelayedTrigger, TriggeredCallback
from donkeydrifter.parts.tub_v2 import TubWriter, TubRotator
from donkeydrifter.utils import *

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def _selected_model_from_disk():
    """无 --model 启动时回退读取 Web UI 持久化的所选模型（selected_model.json）。

    Web UI 侧（routers/drive.py）在用户选择模型后写入该文件；本函数仅读取，
    使「选模型后要求带模型重启」在重启车端进程时真正生效。读取失败静默回退 None。
    """
    candidates = []
    car_dir = os.environ.get("DONKEY_CAR_DIR", "").strip()
    if car_dir:
        candidates.append(os.path.join(os.path.expanduser(car_dir), "selected_model.json"))
    candidates.append(os.path.expanduser("~/mycar/selected_model.json"))

    for path in candidates:
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                model_path = data.get("model_path")
                if model_path:
                    logger.info("从 %s 读取所选模型：%s", path, model_path)
                    return model_path
        except Exception as e:
            logger.warning("读取所选模型失败 %s: %s", path, e)
    return None


def _model_type_for_model_file(model_path):
    """按模型文件扩展名推导 model_type（与 Web 端 routers/drive.py 的映射一致）。

    使「Web 选模型后重启车端」与「--model 显式指定」时无需 --type 也能选对
    解释器（如 .aidem → aidlite_linear 走 NPU）；未知扩展名返回 None 走 myconfig 默认。
    """
    if not model_path:
        return None
    suffix = os.path.splitext(model_path)[1].lower()
    return {
        '.tflite': 'tflite_linear',
        '.trt': 'tensorrt_linear',
        '.aidem': 'aidlite_linear',
        '.ckpt': 'torch_linear',
    }.get(suffix)


def drive(cfg, model_path=None, use_joystick=False, model_type=None,
          camera_type='single', meta=[]):
    """
    Construct a working robotic vehicle from many parts. Each part runs as a
    job in the Vehicle loop, calling either it's run or run_threaded method
    depending on the constructor flag `threaded`. All parts are updated one
    after another at the framerate given in cfg.DRIVE_LOOP_HZ assuming each
    part finishes processing in a timely manner. Parts may have named outputs
    and inputs. The framework handles passing named outputs to parts
    requesting the same named input.
    """
    logger.info(f'PID: {os.getpid()}')

    # 单实例守护：多个 drive 进程会互相抢占后端唯一车端连接（连接风暴、
    # 页面无画面），发现存活实例时拒绝启动并给出明确指引
    from donkeycar.webui_instance import (
        DriveAlreadyRunning, acquire_drive_instance_lock)
    try:
        acquire_drive_instance_lock()
    except DriveAlreadyRunning as exc:
        logger.error(str(exc))
        sys.exit(1)

    if model_path is None:
        model_path = _selected_model_from_disk()
    if cfg.DONKEY_GYM:
        #the simulator will use cuda and then we usually run out of resources
        #if we also try to use cuda. so disable for donkey_gym.
        os.environ["CUDA_VISIBLE_DEVICES"]="-1"

    if model_type is None:
        if cfg.TRAIN_LOCALIZER:
            model_type = "localizer"
        elif cfg.TRAIN_BEHAVIORS:
            model_type = "behavior"
        else:
            model_type = cfg.DEFAULT_MODEL_TYPE
            # .tflite/.aidem 等扩展名蕴含解释器类型，按文件推导优先于 myconfig 默认
            derived = _model_type_for_model_file(model_path)
            if derived:
                logger.info("按扩展名推导 model_type=%s（%s）", derived, model_path)
                model_type = derived

    # Initialize car
    V = dk.vehicle.Vehicle()

    # Initialize logging before anything else to allow console logging
    if cfg.HAVE_CONSOLE_LOGGING:
        logger.setLevel(logging.getLevelName(cfg.LOGGING_LEVEL))
        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter(cfg.LOGGING_FORMAT))
        logger.addHandler(ch)

    if cfg.HAVE_MQTT_TELEMETRY:
        from donkeydrifter.parts.telemetry import MqttTelemetry
        tel = MqttTelemetry(cfg)
        
    #
    # if we are using the simulator, set it up
    #
    sim_cam = add_simulator(V, cfg)


    #
    # setup encoders, odometry and pose estimation
    #
    add_odometry(V, cfg)


    #
    # setup primary camera
    #
    add_camera(V, cfg, camera_type)


    # add lidar
    if cfg.USE_LIDAR:
        from donkeydrifter.parts.lidar import RPLidar
        if cfg.LIDAR_TYPE == 'RP':
            print("adding RP lidar part")
            lidar = RPLidar(lower_limit = cfg.LIDAR_LOWER_LIMIT, upper_limit = cfg.LIDAR_UPPER_LIMIT)
            V.add(lidar, inputs=[],outputs=['lidar/dist_array'], threaded=True)
        if cfg.LIDAR_TYPE == 'YD':
            print("YD Lidar not yet supported")

    if cfg.HAVE_TFMINI:
        from donkeydrifter.parts.tfmini import TFMini
        lidar = TFMini(port=cfg.TFMINI_SERIAL_PORT)
        V.add(lidar, inputs=[], outputs=['lidar/dist'], threaded=True)

    if cfg.SHOW_FPS:
        from donkeydrifter.parts.fps import FrequencyLogger
        V.add(FrequencyLogger(cfg.FPS_DEBUG_INTERVAL),
              outputs=["fps/current", "fps/fps_list"])

    #
    # add the user input controller(s)
    # - this will add the web controller
    # - it will optionally add any configured 'joystick' controller
    #
    has_input_controller = hasattr(cfg, "CONTROLLER_TYPE") and cfg.CONTROLLER_TYPE != "mock"

    # issue #003 热加载：常驻一个可在运行期原子替换模型的容器。有 --model 时启动
    # 即载入；无 --model 且未启用漂移回放时注册空容器，等待 Web 端选模型后直接
    # 热加载，无需重启车端进程。legacy .json（模型结构+权重分离）不支持热切换，
    # 保持原有静态注册路径。
    _full_model_exts = ('.h5', '.trt', '.tflite', '.savedmodel', '.pth',
                        '.aidem', '.ckpt')
    _is_legacy_json = bool(model_path) and ('.json' in model_path) \
        and not any(ext in model_path for ext in _full_model_exts)
    _replay_no_model = bool(getattr(cfg, 'DRIFT_REPLAY_ENABLED', False)) and not model_path
    if _is_legacy_json or _replay_no_model:
        pilot_holder = None
    else:
        pilot_holder = PilotHolder(
            cfg, output_count=3 if cfg.TRAIN_LOCALIZER else 2)

    ctr = add_user_controller(V, cfg, use_joystick, model_loader=pilot_holder)
    # 模拟器帧事件驱动直推 WebRTC 帧缓冲:车辆循环轮询喂帧会被循环负载欠采样
    # (60Hz 源经轮询只采样到 ~52Hz 进编码器),直推后编码器吃满源帧率,
    # 「出帧→被拾取」的轮询等待同时归零。run_threaded 里的 update 保留作兜底
    # (帧缓冲按到达时刻去重,双写不会重复进编码器)。
    if sim_cam is not None and hasattr(sim_cam, "set_frame_sink"):
        sim_cam.set_frame_sink(ctr.frame_buffer.update)

    #
    # convert 'user/steering' to 'user/angle' to be backward compatible with deep learning data
    #
    V.add(Pipe(), inputs=['user/steering'], outputs=['user/angle'])

    #
    # explode the buttons input map into individual output key/values in memory.
    # Parts can consume a single button via inputs=['web/w1'], run_condition='web/w1'.
    #
    V.add(ExplodeDict(V.mem, "web/"), inputs=['web/buttons'])

    # ESC「先点一下刹车才能倒车」确认协议，仅真车执行器需要。
    # 模拟器无 ESC：该过滤器的负向过零首帧钳 0 会让画圈每次过零都产生一次
    # 跳零毛刺（同时进遥测曲线与模拟器执行），故模拟器模式不挂。
    if not getattr(cfg, 'DONKEY_GYM', False):
        th_filter = ThrottleFilter()
        V.add(th_filter, inputs=['user/throttle'], outputs=['user/throttle'])

    #
    # maintain run conditions for user mode and autopilot mode parts.
    #
    V.add(UserPilotCondition(show_pilot_image=getattr(cfg, 'SHOW_PILOT_IMAGE', False)),
          inputs=['user/mode', "cam/image_array", "cam/image_array_trans"],
          outputs=['run_user', "run_pilot", "ui/image_array"])

    class LedConditionLogic:
        def __init__(self, cfg):
            self.cfg = cfg

        def run(self, mode, recording, recording_alert, behavior_state, model_file_changed, track_loc):
            #returns a blink rate. 0 for off. -1 for on. positive for rate.

            if track_loc is not None:
                led.set_rgb(*self.cfg.LOC_COLORS[track_loc])
                return -1

            if model_file_changed:
                led.set_rgb(self.cfg.MODEL_RELOADED_LED_R, self.cfg.MODEL_RELOADED_LED_G, self.cfg.MODEL_RELOADED_LED_B)
                return 0.1
            else:
                led.set_rgb(self.cfg.LED_R, self.cfg.LED_G, self.cfg.LED_B)

            if recording_alert:
                led.set_rgb(*recording_alert)
                return self.cfg.REC_COUNT_ALERT_BLINK_RATE
            else:
                led.set_rgb(self.cfg.LED_R, self.cfg.LED_G, self.cfg.LED_B)

            if behavior_state is not None and model_type == 'behavior':
                r, g, b = self.cfg.BEHAVIOR_LED_COLORS[behavior_state]
                led.set_rgb(r, g, b)
                return -1 #solid on

            if recording:
                return -1 #solid on
            elif mode == 'user':
                return 1
            elif mode == 'local_angle':
                return 0.5
            elif mode == 'local':
                return 0.1
            return 0

    if cfg.HAVE_RGB_LED and not cfg.DONKEY_GYM:
        from donkeydrifter.parts.led_status import RGB_LED
        led = RGB_LED(cfg.LED_PIN_R, cfg.LED_PIN_G, cfg.LED_PIN_B, cfg.LED_INVERT)
        led.set_rgb(cfg.LED_R, cfg.LED_G, cfg.LED_B)

        V.add(LedConditionLogic(cfg), inputs=['user/mode', 'recording', "records/alert", 'behavior/state', 'modelfile/modified', "pilot/loc"],
              outputs=['led/blink_rate'])

        V.add(led, inputs=['led/blink_rate'])

    def get_record_alert_color(num_records):
        col = (0, 0, 0)
        for count, color in cfg.RECORD_ALERT_COLOR_ARR:
            if num_records >= count:
                col = color
        return col

    class RecordTracker:
        def __init__(self):
            self.last_num_rec_print = 0
            self.dur_alert = 0
            self.force_alert = 0

        def run(self, num_records):
            if num_records is None:
                return 0

            if self.last_num_rec_print != num_records or self.force_alert:
                self.last_num_rec_print = num_records

                if num_records % 10 == 0:
                    print("recorded", num_records, "records")

                if num_records % cfg.REC_COUNT_ALERT == 0 or self.force_alert:
                    self.dur_alert = num_records // cfg.REC_COUNT_ALERT * cfg.REC_COUNT_ALERT_CYC
                    self.force_alert = 0

            if self.dur_alert > 0:
                self.dur_alert -= 1

            if self.dur_alert != 0:
                return get_record_alert_color(num_records)

            return 0

    rec_tracker_part = RecordTracker()
    V.add(rec_tracker_part, inputs=["tub/num_records"], outputs=['records/alert'])

    if cfg.AUTO_RECORD_ON_THROTTLE:
        def show_record_count_status():
            rec_tracker_part.last_num_rec_print = 0
            rec_tracker_part.force_alert = 1
        if (cfg.CONTROLLER_TYPE != "pigpio_rc") and (cfg.CONTROLLER_TYPE != "MM1"):  # these controllers don't use the joystick class
            if isinstance(ctr, JoystickController):
                ctr.set_button_down_trigger('circle', show_record_count_status) #then we are not using the circle button. hijack that to force a record count indication
        else:
            
            show_record_count_status()

    #Sombrero
    if cfg.HAVE_SOMBRERO:
        from donkeydrifter.parts.sombrero import Sombrero
        s = Sombrero()

    #IMU
    add_imu(V, cfg)


    # Use the FPV preview, which will show the cropped image output, or the full frame.
    def load_model(kl, model_path):
        start = time.time()
        print('loading model', model_path)
        kl.load(model_path)
        print('finished loading in %s sec.' % (str(time.time() - start)) )

    def load_weights(kl, weights_path):
        start = time.time()
        try:
            print('loading model weights', weights_path)
            kl.model.load_weights(weights_path)
            print('finished loading in %s sec.' % (str(time.time() - start)) )
        except Exception as e:
            print(e)
            print('ERR>> problems loading weights', weights_path)

    def load_model_json(kl, json_fnm):
        start = time.time()
        print('loading model json', json_fnm)
        from tensorflow.python import keras
        try:
            with open(json_fnm, 'r') as handle:
                contents = handle.read()
                kl.model = keras.models.model_from_json(contents)
            print('finished loading json in %s sec.' % (str(time.time() - start)) )
        except Exception as e:
            print(e)
            print("ERR>> problems loading model json", json_fnm)

    #
    # load and configure model for inference
    #
    if model_path or pilot_holder is not None:
        # legacy .json：模型结构 + 权重分离，走静态注册，不支持热切换
        if model_path and _is_legacy_json:
            kl = dk.utils.get_model_by_type(model_type, cfg)
            load_model_json(kl, model_path)
            weights_path = model_path.replace('.json', '.weights')
            load_weights(kl, weights_path)

            def reload_weights(filename):
                weights_path = filename.replace('.json', '.weights')
                load_weights(kl, weights_path)

            model_reload_cb = reload_weights
            pilot_part = kl
        else:
            # 常规格式：由常驻 PilotHolder 持有模型，支持运行期原子替换。
            # 无 --model 时不预载，等待 Web 端 load_model 热加载。
            if model_path:
                if not any(ext in model_path for ext in _full_model_exts):
                    print("ERR>> Unknown extension type on model file!!")
                    return
                pilot_holder.load(model_path, model_type)

                def reload_model(filename):
                    pilot_holder.load(filename, model_type)

                model_reload_cb = reload_model
            else:
                model_reload_cb = None
            pilot_part = pilot_holder

        if model_path:
            # this part will signal visual LED, if connected
            V.add(FileWatcher(model_path, verbose=True),
                  outputs=['modelfile/modified'])

            # these parts will reload the model file, but only when ai is running
            # so we don't interrupt user driving
            V.add(FileWatcher(model_path), outputs=['modelfile/dirty'],
                  run_condition="run_pilot")
            V.add(DelayedTrigger(100), inputs=['modelfile/dirty'],
                  outputs=['modelfile/reload'], run_condition="run_pilot")
            V.add(TriggeredCallback(model_path, model_reload_cb),
                  inputs=["modelfile/reload"], run_condition="run_pilot")

        #
        # collect inputs to model for inference
        #
        if cfg.TRAIN_BEHAVIORS:
            bh = BehaviorPart(cfg.BEHAVIOR_LIST)
            V.add(bh, outputs=['behavior/state', 'behavior/label', "behavior/one_hot_state_array"])
            try:
                ctr.set_button_down_trigger('L1', bh.increment_state)
            except:
                pass

            inputs = ['cam/image_array', "behavior/one_hot_state_array"]

        elif cfg.USE_LIDAR:
            inputs = ['cam/image_array', 'lidar/dist_array']

        elif cfg.HAVE_ODOM:
            inputs = ['cam/image_array', 'enc/speed']

        elif model_type == "imu":
            assert cfg.HAVE_IMU, 'Missing imu parameter in config'

            class Vectorizer:
                def run(self, *components):
                    return components

            V.add(Vectorizer, inputs=['imu/acl_x', 'imu/acl_y', 'imu/acl_z',
                                      'imu/gyr_x', 'imu/gyr_y', 'imu/gyr_z'],
                  outputs=['imu_array'])

            inputs = ['cam/image_array', 'imu_array']
        else:
            inputs = ['cam/image_array']

        #
        # collect model inference outputs
        #
        outputs = ['pilot/angle', 'pilot/throttle']

        if cfg.TRAIN_LOCALIZER:
            outputs.append("pilot/loc")

        #
        # Add image transformations like crop or trapezoidal mask
        # so they get applied at inference time in autopilot mode.
        #
        if hasattr(cfg, 'TRANSFORMATIONS') or hasattr(cfg, 'POST_TRANSFORMATIONS'):
            from donkeydrifter.parts.image_transformations import \
                ImageTransformations

            #
            # add the complete set of pre and post augmentation transformations
            #
            logger.info(f"Adding inference transformations")
            V.add(ImageTransformations(cfg, 'TRANSFORMATIONS',
                                       'POST_TRANSFORMATIONS'),
                  inputs=['cam/image_array'], outputs=['cam/image_array_trans'])
            inputs = ['cam/image_array_trans'] + inputs[1:]

        V.add(pilot_part, inputs=inputs, outputs=outputs, run_condition='run_pilot')

    #
    # 漂移操作回放：用录制的转向/油门时间序列替代模型推理。
    # 与 KerasPilot 互斥（仅在未加载模型且启用回放时注册）。
    # DriftReplayPart 输出 pilot/angle、pilot/throttle（-1~1），
    # 接口与 KerasPilot 同构，下游 DriveMode/ArdPWM 链路不变。
    # 安全：run_condition='run_pilot'（user/mode != 'user' 才生效），
    # 固件侧需 RC CH4 拨到 FULL_AUTO 才接受；Park/mode 随时可接管。
    #
    if getattr(cfg, 'DRIFT_REPLAY_ENABLED', False) and not model_path:
        from donkeydrifter.parts.drift_replay import DriftReplayPart
        replay_part = DriftReplayPart(
            clip_path=cfg.DRIFT_REPLAY_CLIP,
            speed=getattr(cfg, 'DRIFT_REPLAY_SPEED', 1.0),
            loop=getattr(cfg, 'DRIFT_REPLAY_LOOP', 1),
            max_throttle=getattr(cfg, 'DRIFT_REPLAY_MAX_THROTTLE', 0.6),
            max_steering=getattr(cfg, 'DRIFT_REPLAY_MAX_STEERING', 1.0),
            max_delta_throttle=getattr(cfg, 'DRIFT_REPLAY_MAX_DELTA_THROTTLE', 0.2),
            max_delta_steering=getattr(cfg, 'DRIFT_REPLAY_MAX_DELTA_STEERING', 0.3),
            warmup_frames=getattr(cfg, 'DRIFT_REPLAY_WARMUP_FRAMES', 10),
        )
        V.add(replay_part, outputs=['pilot/angle', 'pilot/throttle'],
              run_condition='run_pilot')
        logger.info("Drift replay part enabled (clip=%s)", cfg.DRIFT_REPLAY_CLIP)

    #
    # stop at a stop sign
    #
    if cfg.STOP_SIGN_DETECTOR:
        from donkeydrifter.parts.object_detector.stop_sign_detector import \
            StopSignDetector
        V.add(StopSignDetector(cfg.STOP_SIGN_MIN_SCORE,
                               cfg.STOP_SIGN_SHOW_BOUNDING_BOX,
                               cfg.STOP_SIGN_MAX_REVERSE_COUNT,
                               cfg.STOP_SIGN_REVERSE_THROTTLE),
              inputs=['cam/image_array', 'pilot/throttle'],
              outputs=['pilot/throttle', 'cam/image_array'])
        V.add(ThrottleFilter(), 
              inputs=['pilot/throttle'],
              outputs=['pilot/throttle'])

    #
    # to give the car a boost when starting ai mode in a race.
    # This will also override the stop sign detector so that
    # you can start at a stop sign using launch mode, but
    # will stop when it comes to the stop sign the next time.
    #
    # NOTE: when launch throttle is in effect, pilot speed is set to None
    #
    aiLauncher = AiLaunch(cfg.AI_LAUNCH_DURATION, cfg.AI_LAUNCH_THROTTLE, cfg.AI_LAUNCH_KEEP_ENABLED)
    V.add(aiLauncher,
          inputs=['user/mode', 'pilot/throttle'],
          outputs=['pilot/throttle'])

    #
    # Decide what inputs should change the car's steering and throttle
    # based on the choice of user or autopilot drive mode
    #
    V.add(DriveMode(cfg.AI_THROTTLE_MULT),
          inputs=['user/mode', 'user/angle', 'user/throttle',
                  'pilot/angle', 'pilot/throttle'],
          outputs=['steering', 'throttle'])

    # 转向平滑：滤掉上游瞬时跳变（虚拟摇杆微释放拍零、控制链路抖动），
    # 避免转向阶跃直达模拟器/执行器引发车身弹跳。
    # STEERING_SMOOTHER_ALPHA=1 且 STEERING_SMOOTHER_SLEW_PER_SEC=0 可完全禁用。
    V.add(SteeringSmoother(getattr(cfg, 'STEERING_SMOOTHER_ALPHA', 0.35),
                           getattr(cfg, 'STEERING_SMOOTHER_SLEW_PER_SEC', 8.0)),
          inputs=['steering'], outputs=['steering'])

    # 油门平滑：与转向对称（此前油门裸奔，手抖/像素量化/双时钟采样跳帧直达
    # 曲线与模拟器）。油门比转向更怕时延，参数更跟手：alpha=0.5（60Hz 下
    # τ≈17ms）、slew=6.0/s（0→满油门最快 167ms，只拦毛刺不限制正常操作）。
    # THROTTLE_SMOOTHER_ALPHA=1 且 THROTTLE_SMOOTHER_SLEW_PER_SEC=0 可完全禁用。
    V.add(EmaSmoother(getattr(cfg, 'THROTTLE_SMOOTHER_ALPHA', 0.5),
                      getattr(cfg, 'THROTTLE_SMOOTHER_SLEW_PER_SEC', 6.0)),
          inputs=['throttle'], outputs=['throttle'])


    if (cfg.CONTROLLER_TYPE != "pigpio_rc") and (cfg.CONTROLLER_TYPE != "MM1"):
        if isinstance(ctr, JoystickController):
            ctr.set_button_down_trigger(cfg.AI_LAUNCH_ENABLE_BUTTON, aiLauncher.enable_ai_launch)


    # Ai Recording
    recording_control = ToggleRecording(cfg.AUTO_RECORD_ON_THROTTLE, cfg.RECORD_DURING_AI)
    V.add(recording_control, inputs=['user/mode', "recording"], outputs=["recording"])

    #
    # Setup drivetrain
    #
    add_drivetrain(V, cfg)


    #
    # OLED display setup
    #
    if cfg.USE_SSD1306_128_32:
        from donkeydrifter.parts.oled import OLEDPart
        auto_record_on_throttle = cfg.USE_JOYSTICK_AS_DEFAULT and cfg.AUTO_RECORD_ON_THROTTLE
        oled_part = OLEDPart(cfg.SSD1306_128_32_I2C_ROTATION, cfg.SSD1306_RESOLUTION, auto_record_on_throttle)
        V.add(oled_part, inputs=['recording', 'tub/num_records', 'user/mode'], outputs=[], threaded=True)

    #
    # add tub to save data
    #
    if cfg.USE_LIDAR:
        inputs = ['cam/image_array', 'lidar/dist_array', 'user/angle', 'user/throttle', 'user/mode']
        types = ['image_array', 'nparray','float', 'float', 'str']
    else:
        inputs=['cam/image_array','user/angle', 'user/throttle', 'user/mode']
        types=['image_array','float', 'float','str']

    if cfg.HAVE_ODOM:
        inputs += ['enc/speed']
        types += ['float']

    if cfg.TRAIN_BEHAVIORS:
        inputs += ['behavior/state', 'behavior/label', "behavior/one_hot_state_array"]
        types += ['int', 'str', 'vector']

    if cfg.CAMERA_TYPE == "D435" and cfg.REALSENSE_D435_DEPTH:
        inputs += ['cam/depth_array']
        types += ['gray16_array']

    if cfg.HAVE_IMU or (cfg.CAMERA_TYPE == "D435" and cfg.REALSENSE_D435_IMU):
        inputs += ['imu/acl_x', 'imu/acl_y', 'imu/acl_z',
            'imu/gyr_x', 'imu/gyr_y', 'imu/gyr_z']

        types +=['float', 'float', 'float',
           'float', 'float', 'float']

    # rbx
    if cfg.DONKEY_GYM:
        if cfg.SIM_RECORD_LOCATION:
            inputs += ['pos/pos_x', 'pos/pos_y', 'pos/pos_z', 'pos/speed', 'pos/cte']
            types  += ['float', 'float', 'float', 'float', 'float']
        if cfg.SIM_RECORD_GYROACCEL:
            inputs += ['gyro/gyro_x', 'gyro/gyro_y', 'gyro/gyro_z', 'accel/accel_x', 'accel/accel_y', 'accel/accel_z']
            types  += ['float', 'float', 'float', 'float', 'float', 'float']
        if cfg.SIM_RECORD_VELOCITY:
            inputs += ['vel/vel_x', 'vel/vel_y', 'vel/vel_z']
            types  += ['float', 'float', 'float']
        if cfg.SIM_RECORD_LIDAR:
            inputs += ['lidar/dist_array']
            types  += ['nparray']

    if cfg.RECORD_DURING_AI:
        inputs += ['pilot/angle', 'pilot/throttle']
        types += ['float', 'float']

    if cfg.HAVE_PERFMON:
        from donkeydrifter.parts.perfmon import PerfMonitor
        mon = PerfMonitor(cfg)
        perfmon_outputs = ['perf/cpu', 'perf/mem', 'perf/freq']
        inputs += perfmon_outputs
        types += ['float', 'float', 'float']
        V.add(mon, inputs=[], outputs=perfmon_outputs, threaded=True)

    #
    # Create data storage part
    #
    tub_path = TubHandler(path=cfg.DATA_PATH).create_tub_path() if \
        cfg.AUTO_CREATE_NEW_TUB else cfg.DATA_PATH
    meta += getattr(cfg, 'METADATA', [])

    # RC 手动驾驶（固件 MANUAL 模式）时，车辆实际执行的转向/油门经串口
    # T 帧上行到 rc/steering、rc/throttle，而 Web 通道 user/angle、user/throttle
    # 恒为 0。录制前按固件模式合并：仅 rc/mode==0（MANUAL）且非 park 时用 RC
    # 实际值覆盖 user/angle、user/throttle；其它情况原样透传。不新增 tub 字段，
    # 既有 tub schema（inputs/types 一致性断言）不受影响。须在 ArdPWM*/ArdRc
    # 之后、TubWriter 之前注册；无 rc/* 键的传动链（如仿真）下为安全透传。
    from donkeydrifter.parts.actuator import RcRecordMerge
    V.add(RcRecordMerge(),
          inputs=['user/angle', 'user/throttle',
                  'rc/steering', 'rc/throttle', 'rc/mode', 'rc/park'],
          outputs=['user/angle', 'user/throttle'])

    tub_writer = TubWriter(tub_path, inputs=inputs, types=types, metadata=meta)
    # 每次开始录制（recording 上升沿）自动切换到新 tub，样本计数从 0 开始，
    # 不再向旧 tub 追加；须注册在 TubWriter 之前，保证同一循环内先轮换再写首帧。
    V.add(TubRotator(tub_writer, cfg.DATA_PATH),
          inputs=['recording'], outputs=[])
    V.add(tub_writer, inputs=inputs, outputs=["tub/num_records"], run_condition='recording')

    # Telemetry (we add the same metrics added to the TubHandler
    if cfg.HAVE_MQTT_TELEMETRY:
        from donkeydrifter.parts.telemetry import MqttTelemetry
        tel = MqttTelemetry(cfg)
        telem_inputs, _ = tel.add_step_inputs(inputs, types)
        V.add(tel, inputs=telem_inputs, outputs=["tub/queue_size"], threaded=True)

    if cfg.PUB_CAMERA_IMAGES:
        from donkeydrifter.parts.image import ImgArrToJpg
        from donkeydrifter.parts.network import TCPServeValue
        pub = TCPServeValue("camera")
        V.add(ImgArrToJpg(), inputs=['cam/image_array'], outputs=['jpg/bin'])
        V.add(pub, inputs=['jpg/bin'])

    # 配网 Part（需 ESP32 配网固件配合，默认关闭）
    # 使用独立 Serial2（/dev/ttyS6），不与控制/遥测 Serial1 竞争
    if cfg.PROVISIONING_ENABLED:
        from donkeydrifter.parts.provisioning import ProvisioningPart
        prov = ProvisioningPart(
            serial_port=cfg.PROVISIONING_SERIAL_PORT,
            baudrate=cfg.PROVISIONING_BAUDRATE,
            wifi_interface=cfg.PROVISIONING_WIFI_INTERFACE,
            timeout=cfg.PROVISIONING_SERIAL_TIMEOUT,
        )
        V.add(prov,
              inputs=['provisioning/trigger'],
              outputs=['provisioning/status', 'provisioning/ssid',
                       'provisioning/ip', 'provisioning/error'],
              threaded=True)


    if isinstance(ctr, DriveApiBridge):
        print(f"Web Console Drive 已就绪，请打开浏览器访问 {ctr.web_console_url()}/#/drive")
    if has_input_controller:
        print("You can now move your controller to drive your car.")
        if isinstance(ctr, JoystickController):
            ctr.set_tub(tub_writer.tub)
            ctr.print_controls()

    # run the vehicle
    V.start(rate_hz=cfg.DRIVE_LOOP_HZ, max_loop_count=cfg.MAX_LOOPS)


class ToggleRecording:
    def __init__(self, auto_record_on_throttle, record_in_autopilot):
        """
        Donkeycar Part that manages the recording state.
        """
        self.auto_record_on_throttle = auto_record_on_throttle
        self.record_in_autopilot = record_in_autopilot
        self.recording_latch: bool = None
        self.toggle_latch: bool = False
        self.last_recording = None

    def set_recording(self, recording: bool):
        """
        Set latched recording value to be applied on next call to run()
        :param recording: True to record, False to not record
        """
        self.recording_latch = recording

    def toggle_recording(self):
        """
        Force toggle of recording state on next call to run()
        """
        self.toggle_latch = True

    def run(self, mode: str, recording: bool):
        """
        Set recording based on user/autopilot mode
        :param mode: 'user'|'local_angle'|'local_pilot'
        :param recording: current recording flag
        :return: updated recording flag
        """
        recording_in = recording
        if recording_in != self.last_recording:
            logging.info(f"Recording Change = {recording_in}")

        if self.toggle_latch:
            if self.auto_record_on_throttle:
                logger.info(
                    'auto record on throttle is enabled; ignoring toggle of manual mode.')
            else:
                recording = not self.last_recording
            self.toggle_latch = False

        if self.recording_latch is not None:
            recording = self.recording_latch
            self.recording_latch = None

        if recording and mode != 'user' and not self.record_in_autopilot:
            logging.info("Ignoring recording in auto-pilot mode")
            recording = False

        if self.last_recording != recording:
            logging.info(f"Setting Recording = {recording}")

        self.last_recording = recording

        return recording


class DriveMode:
    def __init__(self, ai_throttle_mult=1.0):
        """
        :param ai_throttle_mult: scale throttle in autopilot mode
        """
        self.ai_throttle_mult = ai_throttle_mult

    def run(self, mode,
            user_steering, user_throttle,
            pilot_steering, pilot_throttle):
        """
        Main final steering and throttle values based on user mode
        :param mode: 'user'|'local_angle'|'local_pilot'
        :param user_steering: steering value in user (manual) mode
        :param user_throttle: throttle value in user (manual) mode
        :param pilot_steering: steering value in autopilot mode
        :param pilot_throttle: throttle value in autopilot mode
        :return: tuple of (steering, throttle) where throttle is
                 scaled by ai_throttle_mult in autopilot mode
        """
        if mode == 'user':
            return user_steering, user_throttle
        elif mode == 'local_angle':
            return pilot_steering if pilot_steering else 0.0, user_throttle
        return (pilot_steering if pilot_steering else 0.0,
               pilot_throttle * self.ai_throttle_mult if pilot_throttle else 0.0)


class ScaleToArdPwm:
    """将 donkeycar 标准值域 -1~1 的 steering/throttle 缩放到 ArdPWM 期望的 -100~100。

    DriftReplayPart/KerasPilot 输出的是 donkeycar 标准 -1~1，而 ArdPWMSteering/
    ArdPWMThrottle 的 LEFT_ANGLE/RIGHT_ANGLE/MAX_THROTTLE 为 -100~100，
    因此需要在 DriveMode 之后、ArdPWM 之前补一层 ×100 缩放。
    """

    def run(self, steering: float, throttle: float) -> tuple[float, float]:
        return steering * 100.0, throttle * 100.0


class UserPilotCondition:
    def __init__(self, show_pilot_image:bool = False) -> None:
        """
        :param show_pilot_image:bool True to show pilot image in pilot mode
                                     False to show user image in pilot mode
        """
        self.show_pilot_image = show_pilot_image

    def run(self, mode, user_image, pilot_image):
        """
        Maintain run condition and which image to show in web ui
        :param mode: 'user'|'local_angle'|'local_pilot'
        :param user_image: image to show in manual (user) pilot
        :param pilot_image: image to show in auto pilot
        :return: tuple of (user-condition, autopilot-condition, web image)
        """
        if mode == 'user':
            return True, False, user_image
        else:
            return False, True, pilot_image if self.show_pilot_image else user_image


def add_user_controller(V, cfg, use_joystick, input_image='ui/image_array',
                        model_loader=None):
    """
    Add the web controller and any other
    configured user input controller.
    :param V: the vehicle pipeline.
              On output this will be modified.
    :param cfg: the configuration (from myconfig.py)
    :return: the controller
    """

    #
    # This web controller will create a web server that is capable
    # of managing steering, throttle, and modes, and more.
    #
    server_url = os.environ.get("DRIVE_API_SERVER_URL") or getattr(cfg, "DRIVE_API_SERVER_URL", None) or "ws://127.0.0.1:8000/api/drive/ws"
    ctr = DriveApiBridge(
        server_url=server_url,
        video_transport=getattr(cfg, "DRIVE_VIDEO_TRANSPORT", "webrtc"),
        video_width=getattr(cfg, "DRIVE_VIDEO_WIDTH", 320),
        video_height=getattr(cfg, "DRIVE_VIDEO_HEIGHT", 240),
        video_fps=getattr(cfg, "DRIVE_VIDEO_FPS", 60),
        webrtc_enabled=getattr(cfg, "DRIVE_WEBRTC_ENABLED", True),
        webrtc_ice_servers=getattr(cfg, "DRIVE_WEBRTC_ICE_SERVERS", None),
        webrtc_video_bitrate=getattr(cfg, "DRIVE_WEBRTC_VIDEO_BITRATE", None),
        webrtc_encoder_tune=getattr(cfg, "DRIVE_WEBRTC_ENCODER_TUNE", None),
        jpeg_quality=getattr(cfg, "DRIVE_VIDEO_JPEG_QUALITY", 95),
        model_loader=model_loader,
    )
    # inputs 顺序必须与 DriveApiBridge.run_threaded 签名严格一致（Vehicle 按位置解包）：
    # (img_arr, num_records, mode, recording, imu_gz, imu_gx, imu_gy,
    #  imu_ax, imu_ay, imu_az, steering, throttle, pilot_angle, pilot_throttle,
    #  rc_steering, rc_throttle, rc_mode, rc_park,
    #  drift_yaw_error, drift_steering_correction, drift_throttle_mode, sim_connected)
    # 非 HAVE_IMU 或 ARDUINO_CONTROLLER 模式下 imu/* key 可能不存在，Memory.get 返回 None，
    # run_threaded 收到 None 后不写入遥测消息（见 RFC 降级说明），无需条件分支。
    # rc/* 来自 ArdRc（固件 T..S.. / M:P 帧上行）：接通 Drive 页 rc 油门/转向曲线、
    # 驾驶模式跟随与 Park 锁定徽标；非 ARDUINO 模式下键不存在，同样走 None 跳过。
    # 尾部 sim/connected 由 add_simulator 的 SimConnectionState 提供（模拟器模式），
    # 真车模式下该 key 不存在、遥测自动省略 sim_connected 字段。
    ctr_inputs = [input_image, 'tub/num_records', 'user/mode', 'recording',
                  'imu/gyr_z', 'imu/gyr_x', 'imu/gyr_y',
                  'imu/acl_x', 'imu/acl_y', 'imu/acl_z',
                  'steering', 'throttle', 'pilot/angle', 'pilot/throttle',
                  'rc/steering', 'rc/throttle', 'rc/mode', 'rc/park',
                  'drift/yaw_error', 'drift/steering_correction', 'drift/throttle_mode',
                  'sim/connected']
    V.add(ctr,
          inputs=ctr_inputs,
          outputs=['user/steering', 'user/throttle', 'user/mode', 'recording', 'web/buttons', 'reconnect_simulator', 'car/mode_cmd', 'reset_car'],
          threaded=True)

    #
    # also add a physical controller if one is configured
    #
    if use_joystick or cfg.USE_JOYSTICK_AS_DEFAULT:
        #
        # RC controller
        #
        if cfg.CONTROLLER_TYPE == "pigpio_rc":  # an RC controllers read by GPIO pins. They typically don't have buttons
            from donkeydrifter.parts.controller import RCReceiver
            ctr = RCReceiver(cfg)
            V.add(
                ctr,
                inputs=['user/mode', 'recording'],
                outputs=['user/steering', 'user/throttle',
                         'user/mode', 'recording'],
                threaded=False)
        else:
            #
            # custom game controller mapping created with
            # `donkey createjs` command
            #
            if cfg.CONTROLLER_TYPE == "custom":  # custom controller created with `donkey createjs` command
                from my_joystick import MyJoystickController
                ctr = MyJoystickController(
                    throttle_dir=cfg.JOYSTICK_THROTTLE_DIR,
                    throttle_scale=cfg.JOYSTICK_MAX_THROTTLE,
                    steering_scale=cfg.JOYSTICK_STEERING_SCALE,
                    auto_record_on_throttle=cfg.AUTO_RECORD_ON_THROTTLE)
                ctr.set_deadzone(cfg.JOYSTICK_DEADZONE)
            elif cfg.CONTROLLER_TYPE == "MM1":
                from donkeydrifter.parts.robohat import RoboHATController
                ctr = RoboHATController(cfg)
            elif cfg.CONTROLLER_TYPE == "mock":
                from donkeydrifter.parts.controller import MockController
                ctr = MockController(steering=cfg.MOCK_JOYSTICK_STEERING,
                                     throttle=cfg.MOCK_JOYSTICK_THROTTLE)
            else:
                #
                # game controller
                #
                from donkeydrifter.parts.controller import get_js_controller
                ctr = get_js_controller(cfg)
                if cfg.USE_NETWORKED_JS:
                    from donkeydrifter.parts.controller import JoyStickSub
                    netwkJs = JoyStickSub(cfg.NETWORK_JS_SERVER_IP)
                    V.add(netwkJs, threaded=True)
                    ctr.js = netwkJs
            V.add(
                ctr,
                inputs=[input_image, 'user/mode', 'recording'],
                outputs=['user/steering', 'user/throttle',
                         'user/mode', 'recording'],
                threaded=True)
    return ctr


def add_simulator(V, cfg):
    # Donkey gym part will output position information if it is configured
    # TODO: the simulation outputs conflict with imu, odometry, kinematics pose estimation and T265 outputs; make them work together.
    if cfg.DONKEY_GYM:
        from donkeydrifter.parts.dgym import DonkeyGymEnv

        # 模拟器出图（cam/image_array）必须等于 NN 输入分辨率 IMAGE_W×IMAGE_H——
        # 它与真机相机路径、TubWriter、模型输入是同一契约；GYM_CONF 缺 img_w/img_h
        # 时 dgym 回退 160x120（与模型/录制错位，首帧推理形状不匹配会带停整个
        # drive 主循环），带旧值同理。渲染分辨率仍由 render_img_w/render_img_h
        # 独立控制，dgym 内部按它出图再下采样回此分辨率。
        sim_conf = dict(cfg.GYM_CONF)
        sim_conf["img_w"] = cfg.IMAGE_W
        sim_conf["img_h"] = cfg.IMAGE_H

        # rbx
        gym = DonkeyGymEnv(cfg.DONKEY_SIM_PATH, host=cfg.SIM_HOST, env_name=cfg.DONKEY_GYM_ENV_NAME, conf=sim_conf,
                           record_location=cfg.SIM_RECORD_LOCATION, record_gyroaccel=cfg.SIM_RECORD_GYROACCEL,
                           record_velocity=cfg.SIM_RECORD_VELOCITY, record_lidar=cfg.SIM_RECORD_LIDAR,
                        #    record_distance=cfg.SIM_RECORD_DISTANCE, record_orientation=cfg.SIM_RECORD_ORIENTATION,
                           delay=cfg.SIM_ARTIFICIAL_LATENCY)
        threaded = True
        inputs = ['steering', 'throttle', 'reconnect_simulator', 'reset_car']
        outputs = ['cam/image_array']

        if cfg.SIM_RECORD_LOCATION:
            outputs += ['pos/pos_x', 'pos/pos_y', 'pos/pos_z', 'pos/speed', 'pos/cte']
        if cfg.SIM_RECORD_GYROACCEL:
            outputs += ['gyro/gyro_x', 'gyro/gyro_y', 'gyro/gyro_z', 'accel/accel_x', 'accel/accel_y', 'accel/accel_z']
        if cfg.SIM_RECORD_VELOCITY:
            outputs += ['vel/vel_x', 'vel/vel_y', 'vel/vel_z']
        if cfg.SIM_RECORD_LIDAR:
            outputs += ['lidar/dist_array']
        # if cfg.SIM_RECORD_DISTANCE:
        #     outputs += ['dist/left', 'dist/right']
        # if cfg.SIM_RECORD_ORIENTATION:
        #     outputs += ['roll', 'pitch', 'yaw']

        V.add(gym, inputs=inputs, outputs=outputs, threaded=threaded)

        class SimConnectionState:
            """把 DonkeyGymEnv 的 TCP 连接状态发布为 sim/connected，供遥测透传到前端。"""

            def __init__(self, cam):
                self._cam = cam

            def run(self):
                return bool(getattr(self._cam, "connected", False))

        V.add(SimConnectionState(gym), outputs=['sim/connected'])
        return gym


def get_camera(cfg):
    """
    Get the configured camera part
    """
    cam = None
    if not cfg.DONKEY_GYM:
        if cfg.CAMERA_TYPE == "PICAM":
            from donkeydrifter.parts.camera import PiCamera
            cam = PiCamera(image_w=cfg.IMAGE_W, image_h=cfg.IMAGE_H, image_d=cfg.IMAGE_DEPTH,
                           vflip=cfg.CAMERA_VFLIP, hflip=cfg.CAMERA_HFLIP)
        elif cfg.CAMERA_TYPE == "WEBCAM":
            from donkeydrifter.parts.camera import Webcam
            cam = Webcam(image_w=cfg.IMAGE_W, image_h=cfg.IMAGE_H, image_d=cfg.IMAGE_DEPTH, framerate=cfg.CAMERA_FRAMERATE, camera_index=cfg.CAMERA_INDEX)
        elif cfg.CAMERA_TYPE == "CVCAM":
            from donkeydrifter.parts.cv import CvCam
            cam = CvCam(image_w=cfg.IMAGE_W, image_h=cfg.IMAGE_H, image_d=cfg.IMAGE_DEPTH, iCam=cfg.CAMERA_INDEX)
        elif cfg.CAMERA_TYPE == "CSIC":
            from donkeydrifter.parts.camera import CSICamera
            cam = CSICamera(image_w=cfg.IMAGE_W, image_h=cfg.IMAGE_H, image_d=cfg.IMAGE_DEPTH,
                            capture_width=cfg.IMAGE_W, capture_height=cfg.IMAGE_H,
                            framerate=cfg.CAMERA_FRAMERATE, gstreamer_flip=cfg.CSIC_CAM_GSTREAMER_FLIP_PARM)
        elif cfg.CAMERA_TYPE == "V4L":
            from donkeydrifter.parts.camera import V4LCamera
            cam = V4LCamera(image_w=cfg.IMAGE_W, image_h=cfg.IMAGE_H, image_d=cfg.IMAGE_DEPTH, framerate=cfg.CAMERA_FRAMERATE)
        elif cfg.CAMERA_TYPE == "IMAGE_LIST":
            from donkeydrifter.parts.camera import ImageListCamera
            cam = ImageListCamera(path_mask=cfg.PATH_MASK)
        elif cfg.CAMERA_TYPE == "LEOPARD":
            from donkeydrifter.parts.leopard_imaging import LICamera
            cam = LICamera(width=cfg.IMAGE_W, height=cfg.IMAGE_H, fps=cfg.CAMERA_FRAMERATE)
        elif cfg.CAMERA_TYPE == "MOCK":
            from donkeydrifter.parts.camera import MockCamera
            cam = MockCamera(image_w=cfg.IMAGE_W, image_h=cfg.IMAGE_H, image_d=cfg.IMAGE_DEPTH)
        else:
            raise(Exception("Unkown camera type: %s" % cfg.CAMERA_TYPE))
    return cam


def add_camera(V, cfg, camera_type):
    """
    Add the configured camera to the vehicle pipeline.

    :param V: the vehicle pipeline.
              On output this will be modified.
    :param cfg: the configuration (from myconfig.py)
    """
    logger.info("cfg.CAMERA_TYPE %s"%cfg.CAMERA_TYPE)
    if camera_type == "stereo":
        if cfg.CAMERA_TYPE == "WEBCAM":
            from donkeydrifter.parts.camera import Webcam

            camA = Webcam(image_w=cfg.IMAGE_W, image_h=cfg.IMAGE_H, image_d=cfg.IMAGE_DEPTH, framerate=cfg.CAMERA_FRAMERATE, camera_index=0)
            camB = Webcam(image_w=cfg.IMAGE_W, image_h=cfg.IMAGE_H, image_d=cfg.IMAGE_DEPTH, framerate=cfg.CAMERA_FRAMERATE, camera_index=1)

        elif cfg.CAMERA_TYPE == "CVCAM":
            from donkeydrifter.parts.cv import CvCam

            camA = CvCam(image_w=cfg.IMAGE_W, image_h=cfg.IMAGE_H, image_d=cfg.IMAGE_DEPTH, iCam = 0)
            camB = CvCam(image_w=cfg.IMAGE_W, image_h=cfg.IMAGE_H, image_d=cfg.IMAGE_DEPTH, iCam = 1)
        else:
            raise(Exception("Unsupported camera type: %s" % cfg.CAMERA_TYPE))

        V.add(camA, outputs=['cam/image_array_a'], threaded=True)
        V.add(camB, outputs=['cam/image_array_b'], threaded=True)

        from donkeydrifter.parts.image import StereoPair

        V.add(StereoPair(), inputs=['cam/image_array_a', 'cam/image_array_b'],
            outputs=['cam/image_array'])
        if cfg.BGR2RGB:
            from donkeydrifter.parts.cv import ImgBGR2RGB
            V.add(ImgBGR2RGB(), inputs=["cam/image_array_a"], outputs=["cam/image_array_a"])
            V.add(ImgBGR2RGB(), inputs=["cam/image_array_b"], outputs=["cam/image_array_b"])

    elif cfg.CAMERA_TYPE == "D435":
        from donkeydrifter.parts.realsense435i import RealSense435i
        cam = RealSense435i(
            enable_rgb=cfg.REALSENSE_D435_RGB,
            enable_depth=cfg.REALSENSE_D435_DEPTH,
            enable_imu=cfg.REALSENSE_D435_IMU,
            device_id=cfg.REALSENSE_D435_ID)
        V.add(cam, inputs=[],
              outputs=['cam/image_array', 'cam/depth_array',
                       'imu/acl_x', 'imu/acl_y', 'imu/acl_z',
                       'imu/gyr_x', 'imu/gyr_y', 'imu/gyr_z'],
              threaded=True)
    else:
        inputs = []
        outputs = ['cam/image_array']
        threaded = True
        cam = get_camera(cfg)
        if cam:
            V.add(cam, inputs=inputs, outputs=outputs, threaded=threaded)
        if cfg.BGR2RGB:
            from donkeydrifter.parts.cv import ImgBGR2RGB
            V.add(ImgBGR2RGB(), inputs=["cam/image_array"], outputs=["cam/image_array"])


def add_odometry(V, cfg, threaded=True):
    """
    If the configuration support odometry, then
    add encoders, odometry and kinematics to the vehicle pipeline
    :param V: the vehicle pipeline.
              On output this may be modified.
    :param cfg: the configuration (from myconfig.py)
    """
    from donkeydrifter.parts.pose import BicyclePose, UnicyclePose

    if cfg.HAVE_ODOM:
        poll_delay_secs = 0.01  # pose estimation runs at 100hz
        kinematics = UnicyclePose(cfg, poll_delay_secs) if cfg.HAVE_ODOM_2 else BicyclePose(cfg, poll_delay_secs)
        V.add(kinematics,
            inputs = ["throttle", "steering", None],
            outputs = ['enc/distance', 'enc/speed', 'pos/x', 'pos/y',
                       'pos/angle', 'vel/x', 'vel/y', 'vel/angle',
                       'nul/timestamp'],
            threaded = threaded)


#
# IMU setup
#
def add_imu(V, cfg):
    imu = None
    if cfg.HAVE_IMU:
        # ARDUINO_CONTROLLER 模式下，IMU 数据由 ArdImu Part 从 ESP32 串口读取
        # （在 add_drivetrain() 中已添加），此处跳过本地 I2C IMU。
        if cfg.DRIVE_TRAIN_TYPE == "ARDUINO_CONTROLLER":
            return imu
        from donkeydrifter.parts.imu import IMU

        imu = IMU(sensor=cfg.IMU_SENSOR, addr=cfg.IMU_ADDRESS,
                  dlp_setting=cfg.IMU_DLP_CONFIG)
        V.add(imu, outputs=['imu/acl_x', 'imu/acl_y', 'imu/acl_z',
                            'imu/gyr_x', 'imu/gyr_y', 'imu/gyr_z'], threaded=True)
    return imu


#
# Drive train setup
#
def add_drivetrain(V, cfg):

    if (not cfg.DONKEY_GYM) and cfg.DRIVE_TRAIN_TYPE != "MOCK":
        from donkeydrifter.parts import actuator, pins
        from donkeydrifter.parts.actuator import TwoWheelSteeringThrottle

        #
        # To make differential drive steer,
        # divide throttle between motors based on the steering value
        #
        is_differential_drive = cfg.DRIVE_TRAIN_TYPE.startswith("DC_TWO_WHEEL")
        if is_differential_drive:
            V.add(TwoWheelSteeringThrottle(),
                  inputs=['throttle', 'steering'],
                  outputs=['left/throttle', 'right/throttle'])

        if cfg.DRIVE_TRAIN_TYPE == "PWM_STEERING_THROTTLE":
            #
            # drivetrain for RC car with servo and ESC.
            # using a PwmPin for steering (servo)
            # and as second PwmPin for throttle (ESC)
            #
            from donkeydrifter.parts.actuator import (PulseController, PWMSteering,
                                                  PWMThrottle)

            dt = cfg.PWM_STEERING_THROTTLE
            steering_controller = PulseController(
                pwm_pin=pins.pwm_pin_by_id(dt["PWM_STEERING_PIN"]),
                pwm_scale=dt["PWM_STEERING_SCALE"],
                pwm_inverted=dt["PWM_STEERING_INVERTED"])
            steering = PWMSteering(controller=steering_controller,
                                            left_pulse=dt["STEERING_LEFT_PWM"],
                                            right_pulse=dt["STEERING_RIGHT_PWM"])

            throttle_controller = PulseController(
                pwm_pin=pins.pwm_pin_by_id(dt["PWM_THROTTLE_PIN"]),
                pwm_scale=dt["PWM_THROTTLE_SCALE"],
                pwm_inverted=dt['PWM_THROTTLE_INVERTED'])
            throttle = PWMThrottle(controller=throttle_controller,
                                                max_pulse=dt['THROTTLE_FORWARD_PWM'],
                                                zero_pulse=dt['THROTTLE_STOPPED_PWM'],
                                                min_pulse=dt['THROTTLE_REVERSE_PWM'])
            V.add(steering, inputs=['steering'], threaded=True)
            V.add(throttle, inputs=['throttle'], threaded=True)

        elif cfg.DRIVE_TRAIN_TYPE == "I2C_SERVO":
            #
            # This driver is DEPRECATED in favor of 'DRIVE_TRAIN_TYPE == "PWM_STEERING_THROTTLE"'
            # This driver will be removed in a future release
            #
            from donkeydrifter.parts.actuator import (PCA9685, PWMSteering,
                                                  PWMThrottle)

            steering_controller = PCA9685(cfg.STEERING_CHANNEL, cfg.PCA9685_I2C_ADDR, busnum=cfg.PCA9685_I2C_BUSNUM)
            steering = PWMSteering(controller=steering_controller,
                                            left_pulse=cfg.STEERING_LEFT_PWM,
                                            right_pulse=cfg.STEERING_RIGHT_PWM)

            throttle_controller = PCA9685(cfg.THROTTLE_CHANNEL, cfg.PCA9685_I2C_ADDR, busnum=cfg.PCA9685_I2C_BUSNUM)
            throttle = PWMThrottle(controller=throttle_controller,
                                            max_pulse=cfg.THROTTLE_FORWARD_PWM,
                                            zero_pulse=cfg.THROTTLE_STOPPED_PWM,
                                            min_pulse=cfg.THROTTLE_REVERSE_PWM)

            V.add(steering, inputs=['steering'], threaded=True)
            V.add(throttle, inputs=['throttle'], threaded=True)

        elif cfg.DRIVE_TRAIN_TYPE == "DC_STEER_THROTTLE":
            dt = cfg.DC_STEER_THROTTLE
            steering = actuator.L298N_HBridge_2pin(
                pins.pwm_pin_by_id(dt['LEFT_DUTY_PIN']),
                pins.pwm_pin_by_id(dt['RIGHT_DUTY_PIN']))
            throttle = actuator.L298N_HBridge_2pin(
                pins.pwm_pin_by_id(dt['FWD_DUTY_PIN']),
                pins.pwm_pin_by_id(dt['BWD_DUTY_PIN']))

            V.add(steering, inputs=['steering'])
            V.add(throttle, inputs=['throttle'])

        elif cfg.DRIVE_TRAIN_TYPE == "DC_TWO_WHEEL":
            dt = cfg.DC_TWO_WHEEL
            left_motor = actuator.L298N_HBridge_2pin(
                pins.pwm_pin_by_id(dt['LEFT_FWD_DUTY_PIN']),
                pins.pwm_pin_by_id(dt['LEFT_BWD_DUTY_PIN']))
            right_motor = actuator.L298N_HBridge_2pin(
                pins.pwm_pin_by_id(dt['RIGHT_FWD_DUTY_PIN']),
                pins.pwm_pin_by_id(dt['RIGHT_BWD_DUTY_PIN']))

            V.add(left_motor, inputs=['left/throttle'])
            V.add(right_motor, inputs=['right/throttle'])

        elif cfg.DRIVE_TRAIN_TYPE == "DC_TWO_WHEEL_L298N":
            dt = cfg.DC_TWO_WHEEL_L298N
            left_motor = actuator.L298N_HBridge_3pin(
                pins.output_pin_by_id(dt['LEFT_FWD_PIN']),
                pins.output_pin_by_id(dt['LEFT_BWD_PIN']),
                pins.pwm_pin_by_id(dt['LEFT_EN_DUTY_PIN']))
            right_motor = actuator.L298N_HBridge_3pin(
                pins.output_pin_by_id(dt['RIGHT_FWD_PIN']),
                pins.output_pin_by_id(dt['RIGHT_BWD_PIN']),
                pins.pwm_pin_by_id(dt['RIGHT_EN_DUTY_PIN']))

            V.add(left_motor, inputs=['left/throttle'])
            V.add(right_motor, inputs=['right/throttle'])

        elif cfg.DRIVE_TRAIN_TYPE == "SERVO_HBRIDGE_2PIN":
            #
            # Servo for steering and HBridge motor driver in 2pin mode for motor
            #
            from donkeydrifter.parts.actuator import (PulseController, PWMSteering,
                                                  PWMThrottle)

            dt = cfg.SERVO_HBRIDGE_2PIN
            steering_controller = PulseController(
                pwm_pin=pins.pwm_pin_by_id(dt['PWM_STEERING_PIN']),
                pwm_scale=dt['PWM_STEERING_SCALE'],
                pwm_inverted=dt['PWM_STEERING_INVERTED'])
            steering = PWMSteering(controller=steering_controller,
                                            left_pulse=dt['STEERING_LEFT_PWM'],
                                            right_pulse=dt['STEERING_RIGHT_PWM'])

            motor = actuator.L298N_HBridge_2pin(
                pins.pwm_pin_by_id(dt['FWD_DUTY_PIN']),
                pins.pwm_pin_by_id(dt['BWD_DUTY_PIN']))

            V.add(steering, inputs=['steering'], threaded=True)
            V.add(motor, inputs=["throttle"])

        elif cfg.DRIVE_TRAIN_TYPE == "SERVO_HBRIDGE_3PIN":
            #
            # Servo for steering and HBridge motor driver in 3pin mode for motor
            #
            from donkeydrifter.parts.actuator import (PulseController, PWMSteering,
                                                  PWMThrottle)

            dt = cfg.SERVO_HBRIDGE_3PIN
            steering_controller = PulseController(
                pwm_pin=pins.pwm_pin_by_id(dt['PWM_STEERING_PIN']),
                pwm_scale=dt['PWM_STEERING_SCALE'],
                pwm_inverted=dt['PWM_STEERING_INVERTED'])
            steering = PWMSteering(controller=steering_controller,
                                            left_pulse=dt['STEERING_LEFT_PWM'],
                                            right_pulse=dt['STEERING_RIGHT_PWM'])

            motor = actuator.L298N_HBridge_3pin(
                pins.output_pin_by_id(dt['FWD_PIN']),
                pins.output_pin_by_id(dt['BWD_PIN']),
                pins.pwm_pin_by_id(dt['DUTY_PIN']))

            V.add(steering, inputs=['steering'], threaded=True)
            V.add(motor, inputs=["throttle"])

        elif cfg.DRIVE_TRAIN_TYPE == "SERVO_HBRIDGE_PWM":
            #
            # This driver is DEPRECATED in favor of 'DRIVE_TRAIN_TYPE == "SERVO_HBRIDGE_2PIN"'
            # This driver will be removed in a future release
            #
            from donkeydrifter.parts.actuator import PWMSteering, ServoBlaster
            steering_controller = ServoBlaster(cfg.STEERING_CHANNEL) #really pin
            # PWM pulse values should be in the range of 100 to 200
            assert(cfg.STEERING_LEFT_PWM <= 200)
            assert(cfg.STEERING_RIGHT_PWM <= 200)
            steering = PWMSteering(controller=steering_controller,
                                   left_pulse=cfg.STEERING_LEFT_PWM,
                                   right_pulse=cfg.STEERING_RIGHT_PWM)

            from donkeydrifter.parts.actuator import Mini_HBridge_DC_Motor_PWM
            motor = Mini_HBridge_DC_Motor_PWM(cfg.HBRIDGE_PIN_FWD, cfg.HBRIDGE_PIN_BWD)

            V.add(steering, inputs=['steering'], threaded=True)
            V.add(motor, inputs=["throttle"])

        elif cfg.DRIVE_TRAIN_TYPE == "MM1":
            from donkeydrifter.parts.robohat import RoboHATDriver
            V.add(RoboHATDriver(cfg), inputs=['steering', 'throttle'])

        elif cfg.DRIVE_TRAIN_TYPE == "PIGPIO_PWM":
            #
            # This driver is DEPRECATED in favor of 'DRIVE_TRAIN_TYPE == "PWM_STEERING_THROTTLE"'
            # This driver will be removed in a future release
            #
            from donkeydrifter.parts.actuator import (PiGPIO_PWM, PWMSteering,
                                                  PWMThrottle)
            steering_controller = PiGPIO_PWM(cfg.STEERING_PWM_PIN, freq=cfg.STEERING_PWM_FREQ,
                                             inverted=cfg.STEERING_PWM_INVERTED)
            steering = PWMSteering(controller=steering_controller,
                                   left_pulse=cfg.STEERING_LEFT_PWM,
                                   right_pulse=cfg.STEERING_RIGHT_PWM)

            throttle_controller = PiGPIO_PWM(cfg.THROTTLE_PWM_PIN, freq=cfg.THROTTLE_PWM_FREQ,
                                             inverted=cfg.THROTTLE_PWM_INVERTED)
            throttle = PWMThrottle(controller=throttle_controller,
                                   max_pulse=cfg.THROTTLE_FORWARD_PWM,
                                   zero_pulse=cfg.THROTTLE_STOPPED_PWM,
                                   min_pulse=cfg.THROTTLE_REVERSE_PWM)
            V.add(steering, inputs=['steering'], threaded=True)
            V.add(throttle, inputs=['throttle'], threaded=True)
    
        elif cfg.DRIVE_TRAIN_TYPE == "VESC":
            from donkeydrifter.parts.actuator import VESC
            logger.info("Creating VESC at port {}".format(cfg.VESC_SERIAL_PORT))
            vesc = VESC(cfg.VESC_SERIAL_PORT,
                          cfg.VESC_MAX_SPEED_PERCENT,
                          cfg.VESC_HAS_SENSOR,
                          cfg.VESC_START_HEARTBEAT,
                          cfg.VESC_BAUDRATE,
                          cfg.VESC_TIMEOUT,
                          cfg.VESC_STEERING_SCALE,
                          cfg.VESC_STEERING_OFFSET
                        )
            V.add(vesc, inputs=['steering', 'throttle'])
            
        elif cfg.DRIVE_TRAIN_TYPE == "ARDUINO_CONTROLLER":
            # This driver is DEPRECATED in favor of 'DRIVE_TRAIN_TYPE == "ARDUINO_CONTROLLER"'
            # This driver will controll Arduino directly via pymata and firmata
            from donkeydrifter.parts.actuator import (ArdPWMSteering,
                                                  ArdPWMThrottle, Arduino)
            arduino_controller = Arduino(cfg)
            steering = ArdPWMSteering(controller=arduino_controller,
                    left_val=cfg.STEERING_LEFT_PWM,
                    right_val=cfg.STEERING_RIGHT_PWM,
                    channel=cfg.STEERING_PWM_CHANNEL)

            throttle = ArdPWMThrottle(controller=arduino_controller,
                    max_pulse=cfg.THROTTLE_FORWARD_PWM,
                    zero_pulse=cfg.THROTTLE_STOPPED_PWM,
                    min_pulse=cfg.THROTTLE_REVERSE_PWM,
                    channel=cfg.THROTTLE_PWM_CHANNEL)

            # donkeycar 标准值域为 -1~1，ArdPWM 期望 -100~100，补缩放层
            V.add(ScaleToArdPwm(), inputs=['steering', 'throttle'],
                  outputs=['steering_ard', 'throttle_ard'])

            #V.add(steering, inputs=['angle'])
            # V.add(steering, inputs=['angle'], outputs=['user/angle'])
            # ArdPWMSteering 在 user 模式透传上游 steering_ard 还原后的 user/angle，
            # 不再用串口 RC 怠速值覆盖，避免录制数据间歇性跳到 0。
            V.add(steering, inputs=['user/mode','steering_ard'], outputs=['user/mode','user/angle'], threaded=True)
            V.add(throttle, inputs=['user/mode','throttle_ard','user/throttle'], outputs=['user/throttle'])
            #V.add(throttle, inputs=['throttle'], threaded=True)

            # RC 接收机（手柄）输入发布到 Memory，供遥测桥上行 web UI 遥测曲线，
            # 及 RcRecordMerge 在 MANUAL 模式录制时合并进 user/* 通道。
            # 输出独立 rc/* 键，不直接覆盖 user/angle，避免录制数据被 RC 怠速值污染。
            # rc/mode、rc/park 来自固件 1Hz M<m>:P<p> 帧，用于 UI 显示 Park 锁定状态。
            from donkeydrifter.parts.actuator import ArdRc
            rc_input = ArdRc(controller=arduino_controller)
            V.add(rc_input, outputs=['rc/steering', 'rc/throttle', 'rc/mode', 'rc/park'])

            # web UI 下发的车控模式命令（car/mode_cmd）经 Serial1 下行到 ESP32，
            # 与遥控器 CH_MODE 双向同步（Issue #223 / Firmware#111）。去重写串口。
            from donkeydrifter.parts.actuator import ArdModeCmd
            mode_cmd = ArdModeCmd(controller=arduino_controller)
            V.add(mode_cmd, inputs=['car/mode_cmd'])

            # 当启用 IMU 时，从 ESP32 串口读取 IMU 数据（ArdImu 共享 arduino_controller 的串口连接）
            if cfg.HAVE_IMU:
                from donkeydrifter.parts.actuator import ArdImu
                imu = ArdImu(controller=arduino_controller)
                V.add(imu, outputs=[
                    'imu/acl_x', 'imu/acl_y', 'imu/acl_z',
                    'imu/gyr_x', 'imu/gyr_y', 'imu/gyr_z',
                ], threaded=True)



def start_drive(cfg, args):
    """Wrapper to start drive mode"""
    model_type = args['--type']
    camera_type = args['--camera']
    drive(cfg, model_path=args['--model'], use_joystick=args['--js'],
          model_type=model_type, camera_type=camera_type,
          meta=args['--meta'])


if __name__ == '__main__':
    args = docopt(__doc__)
    cfg = dk.load_config(myconfig=args['--myconfig'])

    if args['train']:
        print('Use python train.py instead.\n')
    elif args['drive']:
        start_drive(cfg, args)
    else:
        print('No command given. Run `donkey drive` (or `python manage.py drive`) '
              'to start driving.')
