import argparse
import os
import shutil
import socket
import stat
import sys
import logging
import subprocess
import time
import signal
import webbrowser

from progress.bar import IncrementalBar
import donkeycar as dk
from donkeycar.management.joystick_creator import CreateJoystick

from pathlib import Path

from donkeycar.utils import normalize_image, load_image, math
from donkeycar.webui_instance import (
    find_live_instance,
    write_instance,
    remove_instance,
    kill_previous_car_processes,
    read_drive_pids,
    write_drive_pids,
    remove_drive_pid_file,
)

PACKAGE_PATH = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
TEMPLATES_PATH = os.path.join(PACKAGE_PATH, 'templates')


def _ensure_display_and_backend():
    """确保 matplotlib 能在 GUI 窗口中显示图表。

    在无 DISPLAY 的环境下（SSH、Web 后台等），matplotlib 默认使用 agg
    非交互式后端，导致 plt.show() 不弹窗。此函数尝试从当前图形会话
    检测 DISPLAY 和 XAUTHORITY，并切换到 TkAgg 后端。
    """
    import matplotlib

    # 如果已有交互式后端，无需处理
    if matplotlib.get_backend().lower() != 'agg':
        return

    # 尝试从图形会话进程检测 DISPLAY 和 XAUTHORITY
    if not os.environ.get('DISPLAY'):
        _detect_graphical_display()

    # 尝试切换到 TkAgg 后端
    try:
        matplotlib.use('TkAgg')
    except Exception:
        logger.warning(
            '无法启用 TkAgg GUI 后端，图表将不会显示窗口。'
            '请在桌面终端中运行，或使用 --noshow 仅保存图表文件。'
        )


def _detect_graphical_display():
    """从当前用户的 Xwayland/Xorg 进程检测 DISPLAY 和 XAUTHORITY。"""
    try:
        result = subprocess.run(
            ['pgrep', '-a', '-u', str(os.getuid())],
            capture_output=True, text=True, timeout=2
        )
        for line in result.stdout.splitlines():
            if 'Xwayland' not in line and '/Xorg' not in line:
                continue
            pid = line.split()[0]
            environ_path = f'/proc/{pid}/environ'
            with open(environ_path, 'rb') as f:
                environ = f.read().decode('utf-8', errors='replace')
            for entry in environ.split('\0'):
                if entry.startswith('DISPLAY='):
                    os.environ['DISPLAY'] = entry.split('=', 1)[1]
                elif entry.startswith('XAUTHORITY='):
                    os.environ['XAUTHORITY'] = entry.split('=', 1)[1]
            if os.environ.get('DISPLAY'):
                logger.info(
                    f'检测到图形会话: DISPLAY={os.environ["DISPLAY"]}')
                return
    except Exception:
        pass


def _read_drive_pid_file():
    """读取上次 donkey drive 记录的进程 PID 列表。"""
    return read_drive_pids()


def _kill_previous_drive_processes():
    """杀掉上一次启动的车进程（manage.py drive），web 进程保留复用。

    详见 donkeycar/webui_instance.py（issue #127：多链路复用同一 Web UI
    实例，不再全杀）。
    """
    kill_previous_car_processes()

HELP_CONFIG = 'location of config file to use. default: ./config.py'
logger = logging.getLogger(__name__)


# Web UI backend runtime deps. Kept in sync with setup.cfg [fastapi-backend] extra and
# web_ui/backend/requirements.txt. Used for fast pre-flight checks before
# spawning `uvicorn` from the `web` command.
_WEBUI_BACKEND_MODULES = ('fastapi', 'uvicorn', 'multipart', 'websockets')
try:
    import importlib
    _BACKEND_DEPS_OK = all(
        importlib.util.find_spec(name) is not None
        for name in _WEBUI_BACKEND_MODULES
    )
except Exception:
    _BACKEND_DEPS_OK = False


def make_dir(path):
    real_path = os.path.expanduser(path)
    print('making dir ', real_path)
    if not os.path.exists(real_path):
        os.makedirs(real_path)
    return real_path


def load_config(config_path, myconfig='myconfig.py'):
    """
    load a config from the given path
    """
    conf = os.path.expanduser(config_path)
    if not os.path.exists(conf):
        logger.error(f"No config file at location: {conf}. Add --config to "
                     f"specify location or run from dir containing config.py.")
        return None

    try:
        cfg = dk.load_config(conf, myconfig)
    except Exception as e:
        logger.error(f"Exception {e} while loading config from {conf}")
        return None

    return cfg


class BaseCommand(object):
    pass


class CreateCar(BaseCommand):

    def parse_args(self, args):
        parser = argparse.ArgumentParser(prog='createcar', usage='%(prog)s [options]')
        parser.add_argument('--path', default=None, help='path where to create car folder')
        parser.add_argument('--template', default=None, help='name of car template to use')
        parser.add_argument('--overwrite', action='store_true', help='should replace existing files')
        parsed_args = parser.parse_args(args)
        return parsed_args

    def run(self, args):
        args = self.parse_args(args)
        self.create_car(path=args.path, template=args.template, overwrite=args.overwrite)

    def create_car(self, path, template='complete', overwrite=False):
        """
        This script sets up the folder structure for donkey to work.
        It must run without donkey installed so that people installing with
        docker can build the folder structure for docker to mount to.
        """

        # these are neeeded incase None is passed as path
        path = path or '~/mycar'
        template = template or 'complete'
        print(f"Creating car folder: {path}")
        path = make_dir(path)

        print("Creating data & model folders.")
        folders = ['models', 'data', 'data_cache','logs']
        folder_paths = [os.path.join(path, f) for f in folders]
        for fp in folder_paths:
            make_dir(fp)

        # add car application and config files if they don't exist
        app_template_path = os.path.join(TEMPLATES_PATH, template+'.py')
        config_template_path = os.path.join(TEMPLATES_PATH, 'cfg_' + template + '.py')
        myconfig_template_path = os.path.join(TEMPLATES_PATH, 'myconfig.py')
        train_template_path = os.path.join(TEMPLATES_PATH, 'train.py')
        car_app_path = os.path.join(path, 'manage.py')
        car_config_path = os.path.join(path, 'config.py')
        mycar_config_path = os.path.join(path, 'myconfig.py')
        train_app_path = os.path.join(path, 'train.py')

        if os.path.exists(car_app_path) and not overwrite:
            print('Car app already exists. Delete it and rerun createcar to replace.')
        else:
            print(f"Copying car application template: {template}")
            shutil.copyfile(app_template_path, car_app_path)
            os.chmod(car_app_path, stat.S_IRWXU)

        if os.path.exists(car_config_path) and not overwrite:
            print('Car config already exists. Delete it and rerun createcar to replace.')
        else:
            print("Copying car config defaults. Adjust these before starting your car.")
            shutil.copyfile(config_template_path, car_config_path)

        if os.path.exists(train_app_path) and not overwrite:
            print('Train already exists. Delete it and rerun createcar to replace.')
        else:
            print("Copying train script. Adjust these before starting your car.")
            shutil.copyfile(train_template_path, train_app_path)
            os.chmod(train_app_path, stat.S_IRWXU)

        if not os.path.exists(mycar_config_path):
            print("Copying my car config overrides")
            shutil.copyfile(myconfig_template_path, mycar_config_path)
            # now copy file contents from config to myconfig, with all lines
            # commented out.
            cfg = open(car_config_path, "rt")
            mcfg = open(mycar_config_path, "at")
            copy = False
            for line in cfg:
                if "import os" in line:
                    copy = True
                if copy:
                    mcfg.write("# " + line)
            cfg.close()
            mcfg.close()

        print("Donkey setup complete.")


class UpdateCar(BaseCommand):
    '''
    always run in the base ~/mycar dir to get latest
    '''

    def parse_args(self, args):
        parser = argparse.ArgumentParser(prog='update', usage='%(prog)s [options]')
        parser.add_argument('--template', default=None, help='name of car template to use')
        parsed_args = parser.parse_args(args)
        return parsed_args

    def run(self, args):
        args = self.parse_args(args)
        cc = CreateCar()
        cc.create_car(path=".", overwrite=True, template=args.template)


class FindCar(BaseCommand):
    def parse_args(self, args):
        pass

    def run(self, args):
        print('Looking up your computer IP address...')
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        print('Your IP address: %s ' % s.getsockname()[0])
        s.close()

        print("Finding your car's IP address...")
        cmd = "sudo nmap -sP " + ip + "/24 | awk '/^Nmap/{ip=$NF}/B8:27:EB/{print ip}'"
        cmdRPi4 = "sudo nmap -sP " + ip + "/24 | awk '/^Nmap/{ip=$NF}/DC:A6:32/{print ip}'"
        print("Your car's ip address is:")
        os.system(cmd)
        os.system(cmdRPi4)


class CalibrateCar(BaseCommand):

    def parse_args(self, args):
        parser = argparse.ArgumentParser(prog='calibrate', usage='%(prog)s [options]')
        parser.add_argument(
            '--pwm-pin',
            help="The PwmPin specifier of pin to calibrate, like 'RPI_GPIO.BOARD.33' or 'PCA9685.1:40.13'")
        parser.add_argument('--channel', default=None, help="The PCA9685 channel you'd like to calibrate [0-15]")
        parser.add_argument(
            '--address',
            default='0x40',
            help="The i2c address of PCA9685 you'd like to calibrate [default 0x40]")
        parser.add_argument(
            '--bus',
            default=None,
            help="The i2c bus of PCA9685 you'd like to calibrate [default autodetect]")
        parser.add_argument('--pwmFreq', default=60, help="The frequency to use for the PWM")
        parser.add_argument(
            '--arduino',
            dest='arduino',
            action='store_true',
            help='Use arduino pin for PWM (calibrate pin=<channel>)')
        parser.set_defaults(arduino=False)
        parsed_args = parser.parse_args(args)
        return parsed_args

    def run(self, args):
        args = self.parse_args(args)

        if args.arduino:
            from donkeycar.parts.actuator import ArduinoFirmata

            channel = int(args.channel)
            arduino_controller = ArduinoFirmata(servo_pin=channel)
            print('init Arduino PWM on pin %d' % (channel))
            input_prompt = "Enter a PWM setting to test ('q' for quit) (0-180): "

        elif args.pwm_pin is not None:
            from donkeycar.parts.actuator import PulseController
            from donkeycar.parts import pins

            pwm_pin = None
            try:
                pwm_pin = pins.pwm_pin_by_id(args.pwm_pin)
            except ValueError as e:
                print(e)
                print("See pins.py for a description of pin specification strings.")
                exit(-1)
            print(f'init pin {args.pwm_pin}')
            freq = int(args.pwmFreq)
            print(f"Using PWM freq: {freq}")
            c = PulseController(pwm_pin)
            input_prompt = "Enter a PWM setting to test ('q' for quit) (0-1500): "
            print()

        else:
            from donkeycar.parts.actuator import PCA9685
            from donkeycar.parts.sombrero import Sombrero

            Sombrero()  # setup pins for Sombrero hat

            channel = int(args.channel)
            busnum = None
            if args.bus:
                busnum = int(args.bus)
            address = int(args.address, 16)
            print('init PCA9685 on channel %d address %s bus %s' % (channel, str(hex(address)), str(busnum)))
            freq = int(args.pwmFreq)
            print(f"Using PWM freq: {freq}")
            c = PCA9685(channel, address=address, busnum=busnum, frequency=freq)
            input_prompt = "Enter a PWM setting to test ('q' for quit) (0-1500): "
            print()

        while True:
            try:
                val = input(input_prompt)
                if val == 'q' or val == 'Q':
                    break
                pmw = int(val)
                if args.arduino == True:
                    arduino_controller.set_pulse(channel, pmw)
                else:
                    c.run(pmw)
            except KeyboardInterrupt:
                print("\nKeyboardInterrupt received, exit.")
                break
            except Exception as ex:
                print(f"Oops, {ex}")


class MakeMovieShell(BaseCommand):
    '''
    take the make movie args and then call make movie command
    with lazy imports
    '''
    def __init__(self):
        self.deg_to_rad = math.pi / 180.0

    def parse_args(self, args):
        parser = argparse.ArgumentParser(prog='makemovie')
        parser.add_argument('--tub', help='The tub to make movie from')
        parser.add_argument(
            '--out',
            default='tub_movie.mp4',
            help='The movie filename to create. default: tub_movie.mp4')
        parser.add_argument('--config', default='./config.py', help=HELP_CONFIG)
        parser.add_argument('--model', default=None, help='the model to use to show control outputs')
        parser.add_argument('--type', default=None, required=False, help='the model type to load')
        parser.add_argument('--salient', action="store_true", help='should we overlay salient map showing activations')
        parser.add_argument('--start', type=int, default=0, help='first frame to process')
        parser.add_argument('--end', type=int, default=-1, help='last frame to process')
        parser.add_argument('--scale', type=int, default=2, help='make image frame output larger by X mult')
        parser.add_argument(
            '--draw-user-input',
            default=True, action='store_false',
            help='show user input on the video')
        parsed_args = parser.parse_args(args)
        return parsed_args, parser

    def run(self, args):
        '''
        Load the images from a tub and create a movie from them.
        Movie
        '''
        args, parser = self.parse_args(args)

        from donkeycar.management.makemovie import MakeMovie

        mm = MakeMovie()
        mm.run(args, parser)


class ShowHistogram(BaseCommand):

    def parse_args(self, args):
        parser = argparse.ArgumentParser(prog='tubhist',
                                         usage='%(prog)s [options]')
        parser.add_argument('--tub', nargs='+', help='paths to tubs')
        parser.add_argument('--record', default=None,
                            help='name of record to create histogram')
        parser.add_argument('--out', default=None,
                            help='path where to save histogram end with .png')
        parsed_args = parser.parse_args(args)
        return parsed_args

    def show_histogram(self, tub_paths, record_name, out):
        """
        Produce a histogram of record type frequency in the given tub
        """
        _ensure_display_and_backend()
        import pandas as pd
        from matplotlib import pyplot as plt
        from donkeycar.parts.tub_v2 import Tub

        output = out or os.path.basename(tub_paths)
        path_list = tub_paths.split(",")
        records = [record for path in path_list for record
                   in Tub(path, read_only=True)]
        df = pd.DataFrame(records)
        df.drop(columns=["_index", "_timestamp_ms"], inplace=True)
        # this prints it to screen
        if record_name is not None:
            df[record_name].hist(bins=50)
        else:
            df.hist(bins=50)

        try:
            if out is not None:
                filename = output
            else:
                if record_name is not None:
                    filename = f"{output}_hist_{record_name.replace('/', '_')}.png"
                else:
                    filename = f"{output}_hist.png"
            plt.savefig(filename)
            logger.info(f'saving image to: {filename}')
        except Exception as e:
            logger.error(str(e))
        plt.show()

    def run(self, args):
        args = self.parse_args(args)
        if isinstance(args.tub, list):
            args.tub = ','.join(args.tub)
        self.show_histogram(args.tub, args.record, args.out)


class ShowCnnActivations(BaseCommand):

    def __init__(self):
        _ensure_display_and_backend()
        import matplotlib.pyplot as plt
        self.plt = plt

    def get_activations(self, image_path, model_path, cfg):
        '''
        Extracts features from an image

        returns activations/features
        '''
        from tensorflow.python.keras.models import load_model, Model

        model_path = os.path.expanduser(model_path)
        image_path = os.path.expanduser(image_path)

        model = load_model(model_path, compile=False)
        image = load_image(image_path, cfg)[None, ...]

        conv_layer_names = self.get_conv_layers(model)
        input_layer = model.get_layer(name='img_in').input
        activations = []
        for conv_layer_name in conv_layer_names:
            output_layer = model.get_layer(name=conv_layer_name).output

            layer_model = Model(inputs=[input_layer], outputs=[output_layer])
            activations.append(layer_model.predict(image)[0])
        return activations

    def create_figure(self, activations):
        import math
        cols = 6

        for i, layer in enumerate(activations):
            fig = self.plt.figure()
            fig.suptitle(f'Layer {i+1}')

            print(f'layer {i+1} shape: {layer.shape}')
            feature_maps = layer.shape[2]
            rows = math.ceil(feature_maps / cols)

            for j in range(feature_maps):
                self.plt.subplot(rows, cols, j + 1)

                self.plt.imshow(layer[:, :, j])

        self.plt.show()

    def get_conv_layers(self, model):
        conv_layers = []
        for layer in model.layers:
            if layer.__class__.__name__ == 'Conv2D':
                conv_layers.append(layer.name)
        return conv_layers

    def parse_args(self, args):
        parser = argparse.ArgumentParser(prog='cnnactivations', usage='%(prog)s [options]')
        parser.add_argument('--image', help='path to image')
        parser.add_argument('--model', default=None, help='path to model')
        parser.add_argument('--config', default='./config.py', help=HELP_CONFIG)

        parsed_args = parser.parse_args(args)
        return parsed_args

    def run(self, args):
        args = self.parse_args(args)
        cfg = load_config(args.config)
        activations = self.get_activations(args.image, args.model, cfg)
        self.create_figure(activations)


class ShowPredictionPlots(BaseCommand):

    def plot_predictions(self, cfg, tub_paths, model_path, limit, model_type,
                         noshow, dark=False):
        """
        Plot model predictions for angle and throttle against data from tubs.
        """
        _ensure_display_and_backend()
        import matplotlib.pyplot as plt
        import pandas as pd
        from pathlib import Path
        from donkeycar.pipeline.types import TubDataset

        model = None
        if model_path:
            model_path = os.path.expanduser(model_path)
            model = dk.utils.get_model_by_type(model_type, cfg)
            # This just gets us the text for the plot title:
            if model_type is None:
                model_type = cfg.DEFAULT_MODEL_TYPE
            model.load(model_path)

        user_angles = []
        user_throttles = []
        pilot_angles = []
        pilot_throttles = []

        base_path = Path(os.path.expanduser(tub_paths)).absolute().as_posix()
        seq_size = model.seq_size() if model else 0
        dataset = TubDataset(config=cfg, tub_paths=[base_path],
                             seq_size=seq_size)
        records = dataset.get_records()[:limit]
        bar = IncrementalBar('Inferencing', max=len(records))

        for tub_record in records:
            if model:
                input_dict = model.x_transform(
                    tub_record, lambda x: normalize_image(x))
                pilot_angle, pilot_throttle = \
                    model.inference_from_dict(input_dict)
                pilot_angles.append(pilot_angle)
                pilot_throttles.append(pilot_throttle)

            user_angle = tub_record.underlying['user/angle']
            user_throttle = tub_record.underlying['user/throttle']
            user_angles.append(user_angle)
            user_throttles.append(user_throttle)
            bar.next()

        bar.finish()
        
        if model:
            angles_df = pd.DataFrame({'user_angle': user_angles,
                                      'pilot_angle': pilot_angles})
            throttles_df = pd.DataFrame({'user_throttle': user_throttles,
                                         'pilot_throttle': pilot_throttles})
        else:
            angles_df = pd.DataFrame({'user_angle': user_angles})
            throttles_df = pd.DataFrame({'user_throttle': user_throttles})

        if dark:
            plt.style.use('dark_background')
        fig = plt.figure('Tub Plot')
        fig.set_layout_engine('tight')
        title = f"Tub Plot\nTubs: {tub_paths}"
        if model:
            title += f"\nModel: {model_path}\nType: {model_type}"
        fig.suptitle(title)
        ax1 = fig.add_subplot(211)
        ax2 = fig.add_subplot(212)
        angles_df.plot(ax=ax1)
        throttles_df.plot(ax=ax2)
        ax1.legend(loc=4)
        ax2.legend(loc=4)
        if model_path:
            plt.savefig(model_path + '_pred.png')
            logger.info(f'Saving tubplot at {model_path}_pred.png')
        if not noshow:
            plt.show()

    def parse_args(self, args):
        parser = argparse.ArgumentParser(prog='tubplot', usage='%(prog)s [options]')
        parser.add_argument('--tub', nargs='+', help='The tub to make plot from')
        parser.add_argument('--model', default=None, help='model for predictions')
        parser.add_argument('--limit', type=int, default=1000, help='how many records to process')
        parser.add_argument('--type', default=None, help='model type')
        parser.add_argument('--noshow', default=False, action="store_true",
                            help='if plot is shown in window')
        parser.add_argument('--config', default='./config.py', help=HELP_CONFIG)

        parsed_args = parser.parse_args(args)
        return parsed_args

    def run(self, args):
        args = self.parse_args(args)
        args.tub = ','.join(args.tub)
        cfg = load_config(args.config)
        self.plot_predictions(cfg, args.tub, args.model, args.limit,
                              args.type, args.noshow)


class Evaluate(BaseCommand):
    """量化评估模型在 tub 上的 angle/throttle 预测误差。

    输出与真实标签的相关系数 corr、MAE、RMSE、mean_err，用于客观判断模型是否
    真正学到了转向/油门信号（corr 接近 0 即退化为"预测均值/预测多数类"）。
    不传 --model 时只输出标签分布，便于判断数据是否均衡。
    """

    def parse_args(self, args):
        parser = argparse.ArgumentParser(prog='evaluate',
                                         usage='%(prog)s [options]')
        parser.add_argument('--tub', nargs='+', help='tub data for evaluation')
        parser.add_argument('--model', default=None, help='model to evaluate')
        parser.add_argument('--type', default=None,
                            help='model type, defaults to '
                                 'config.DEFAULT_MODEL_TYPE')
        parser.add_argument('--config', default='./config.py', help=HELP_CONFIG)
        parser.add_argument('--out', default=None,
                            help='path to write results as JSON')
        parsed_args = parser.parse_args(args)
        return parsed_args

    def _metrics(self, y_true, y_pred):
        import numpy as np
        y_true = np.asarray(y_true, dtype=np.float64)
        y_pred = np.asarray(y_pred, dtype=np.float64)
        err = y_true - y_pred
        corr = None
        if np.std(y_true) > 0 and np.std(y_pred) > 0:
            corr = float(np.corrcoef(y_true, y_pred)[0, 1])
        return {
            'count': int(len(y_true)),
            'corr': corr,
            'mae': float(np.mean(np.abs(err))),
            'rmse': float(np.sqrt(np.mean(err ** 2))),
            'mean_err': float(np.mean(err)),
        }

    @staticmethod
    def _angle_health_warnings(stats):
        """根据 angle 标签分布给出数据健康度告警。

        阈值基于实测结论：当中间幅度转向样本不足、或左右转向严重失衡、或
        直行帧占比过高时，angle 回归会退化为"预测均值/预测多数类"，最终
        angle corr 会接近 0（实测：mid_ratio=3.2% / left_ratio=7.9% 时
        corr≈0；重新采集均衡数据 mid_ratio=16% / left_ratio=37% 后
        corr≈0.99）。返回告警文案列表，健康时为空列表。
        """
        warnings = []

        mid = stats.get('mid_ratio')
        if mid is not None and mid < 0.05:
            warnings.append(
                '数据健康度差：中间幅度转向样本 mid_ratio 仅 %.1f%%（<5%%），'
                '模型会退化为"预测均值"，angle corr 会接近 0。'
                '建议重新采集平滑连续转向数据，覆盖 0.05~0.5 的中间幅度。'
                % (mid * 100))

        left = stats.get('left_ratio')
        right = stats.get('right_ratio')
        if left is not None and right is not None and \
                (left < 0.1 or right < 0.1):
            warnings.append(
                '数据健康度差：左右转向样本严重失衡（left=%.1f%%, '
                'right=%.1f%%），一侧占比低于 10%%。建议双向均衡采集。'
                % (left * 100, right * 100))

        straight = stats.get('abs_lt_0.05_ratio')
        if straight is not None and straight > 0.7:
            warnings.append(
                '数据健康度差：直行帧占比 %.1f%%（>70%%），有效转向样本过少。'
                '建议提高转向帧比例。' % (straight * 100))

        return warnings

    def run(self, args):
        args = self.parse_args(args)
        args.tub = ','.join(args.tub)
        cfg = load_config(args.config)

        import numpy as np
        from donkeycar.pipeline.types import TubDataset

        model = None
        model_type = args.type
        if args.model:
            if model_type is None:
                model_type = cfg.DEFAULT_MODEL_TYPE
            model = dk.utils.get_model_by_type(model_type, cfg)
            model.load(os.path.expanduser(args.model))

        tub_paths = [os.path.expanduser(t) for t in args.tub.split(',')]
        dataset = TubDataset(config=cfg, tub_paths=tub_paths,
                             seq_size=model.seq_size() if model else 0)
        records = dataset.get_records()

        user_angles = []
        user_throttles = []
        pilot_angles = []
        pilot_throttles = []
        for r in records:
            user_angles.append(float(r.underlying['user/angle']))
            user_throttles.append(float(r.underlying['user/throttle']))
            if model:
                img = r.image()
                a, t = model.run(img)
                pilot_angles.append(float(a))
                pilot_throttles.append(float(t))
        dataset.close()

        result = {
            'records': len(records),
            'model': os.path.expanduser(args.model) if args.model else None,
            'type': model_type,
        }
        if model:
            result['angle'] = self._metrics(user_angles, pilot_angles)
            result['throttle'] = self._metrics(user_throttles, pilot_throttles)
            print(f"records: {result['records']}")
            print(f"angle:   {result['angle']}")
            print(f"throttle: {result['throttle']}")
        else:
            a = np.asarray(user_angles)
            t = np.asarray(user_throttles)
            abs_a = np.abs(a)
            result['angle_stats'] = {
                'mean': float(a.mean()), 'std': float(a.std()),
                'min': float(a.min()), 'max': float(a.max()),
                # 转向幅度三档占比（直行 / 中间幅度 / 大转向），三者相加为 1；
                # 中间幅度缺失是"模型学不到连续转向"的典型数据问题。
                'abs_lt_0.05_ratio': float(np.mean(abs_a < 0.05)),
                'mid_ratio': float(np.mean((abs_a >= 0.05) & (abs_a <= 0.5))),
                'hard_ratio': float(np.mean(abs_a > 0.5)),
                # 左右对称性：left+right+zero 相加为 1，偏差过大说明转向样本左右不均衡。
                'left_ratio': float(np.mean(a < 0)),
                'right_ratio': float(np.mean(a > 0)),
            }
            result['throttle_stats'] = {
                'mean': float(t.mean()), 'std': float(t.std()),
                'min': float(t.min()), 'max': float(t.max()),
            }
            warnings = self._angle_health_warnings(result['angle_stats'])
            if warnings:
                result['warnings'] = warnings
            print(f"records: {result['records']}")
            print(f"user/angle stats:   {result['angle_stats']}")
            print(f"user/throttle stats: {result['throttle_stats']}")
            if warnings:
                print("health warnings:")
                for w in warnings:
                    print(f"  - {w}")
            else:
                print("health warnings: none (数据分布健康)")

        if args.out:
            import json
            with open(os.path.expanduser(args.out), 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            print(f"wrote {args.out}")


class Train(BaseCommand):

    def parse_args(self, args):
        HELP_FRAMEWORK = 'the AI framework to use (tensorflow|pytorch). ' \
                         'Defaults to config.DEFAULT_AI_FRAMEWORK'
        parser = argparse.ArgumentParser(prog='train', usage='%(prog)s [options]')
        parser.add_argument('--tub', nargs='+', help='tub data for training')
        parser.add_argument('--model', default=None, help='output model name')
        parser.add_argument('--type', default=None, help='model type')
        parser.add_argument('--config', default='./config.py', help=HELP_CONFIG)
        parser.add_argument('--myconfig', default='./myconfig.py',
                            help='file name of myconfig file, defaults to '
                                 'myconfig.py')
        parser.add_argument('--framework',
                            choices=['tensorflow', 'pytorch', None],
                            required=False,
                            help=HELP_FRAMEWORK)
        parser.add_argument('--checkpoint', type=str,
                            help='location of checkpoint to resume training from')
        parser.add_argument('--transfer', type=str, help='transfer model')
        parser.add_argument('--comment', type=str,
                            help='comment added to model database - use '
                                 'double quotes for multiple words')
        parsed_args = parser.parse_args(args)
        return parsed_args

    def run(self, args):
        args = self.parse_args(args)
        args.tub = ','.join(args.tub)
        my_cfg = args.myconfig
        cfg = load_config(args.config, my_cfg)
        framework = args.framework if args.framework \
            else getattr(cfg, 'DEFAULT_AI_FRAMEWORK', 'tensorflow')

        if framework == 'tensorflow':
            from donkeycar.pipeline.training import train
            train(cfg, args.tub, args.model, args.type, args.transfer,
                  args.comment)
        elif framework == 'pytorch':
            from donkeycar.parts.pytorch.torch_train import train
            train(cfg, args.tub, args.model, args.type,
                  checkpoint_path=args.checkpoint)
        else:
            logger.error(f"Unrecognized framework: {framework}. Please specify "
                         f"one of 'tensorflow' or 'pytorch'")


class ModelDatabase(BaseCommand):

    def parse_args(self, args):
        parser = argparse.ArgumentParser(prog='models',
                                         usage='%(prog)s [options]')
        parser.add_argument('--config', default='./config.py', help=HELP_CONFIG)
        parser.add_argument('--group', action="store_true",
                            default=False,
                            help='group tubs and plot separately')
        parsed_args = parser.parse_args(args)
        return parsed_args

    def run(self, args):
        from donkeycar.pipeline.database import PilotDatabase
        args = self.parse_args(args)
        cfg = load_config(args.config)
        p = PilotDatabase(cfg)
        pilot_txt, tub_txt, _ = p.pretty_print(args.group)
        print(pilot_txt)
        print(tub_txt)


class Gui(BaseCommand):
    def run(self, args):
        from donkeycar.management.ui.ui import main
        main()


class Tui(BaseCommand):
    def run(self, args):
        from donkeycar.management.tui import main
        main()


class Web(BaseCommand):
    def parse_args(self, args):
        parser = argparse.ArgumentParser(prog='web', usage='%(prog)s [options]')
        parser.add_argument('--path', default='/home/dkc/projects/donkeycar/web_ui',
                            help='web_ui 根目录路径 (默认: /home/dkc/projects/donkeycar/web_ui)')
        parser.add_argument('--frontend-port', type=int, default=5188,
                            help='前端端口 (默认: 5188)')
        parser.add_argument('--backend-port', type=int, default=8000,
                            help='后端端口 (默认: 8000)')
        parser.add_argument('--backend-host', default='0.0.0.0',
                            help='后端监听地址 (默认: 0.0.0.0)')
        parser.add_argument('--install-deps', action='store_true',
                            help='启动前自动安装缺失的前后端依赖 (等价于先运行 `donkey installweb`)')
        parser.add_argument('--open', action='store_true',
                            help='启动后自动打开浏览器')
        parser.add_argument('--route', default='/',
                            help='自动打开的前端路由，HashRouter 路由会转换为 /#/route')
        parser.add_argument('--dev', action='store_true',
                            help='开发模式：用 Vite dev 服务器起前端（HMR 热更新，页面切换明显慢于生产构建）。'
                                 '默认为生产模式：构建 dist 后由后端静态托管（#135）')
        parser.add_argument('--debug', action='store_true',
                            help='启用 DEBUG 日志模式 (默认仅输出 WARNING 及以上级别日志)')
        return parser.parse_args(args)

    def run(self, args):
        args = self.parse_args(args)

        # 已有存活的 Web UI 实例则直接复用，不再重复拉起（issue #127）
        inst = find_live_instance()
        if inst:
            print(f'检测到运行中的 Web UI 实例 '
                  f'(backend=:{inst["backend_port"]} frontend=:{inst["frontend_port"]})，'
                  '复用已有实例，不重复启动')
            if args.open:
                reuse_url = self._build_frontend_url(inst['frontend_port'], args.route)
                self._open_browser_when_frontend_ready(inst['frontend_port'], reuse_url)
            return

        frontend_proc, backend_proc, frontend_port, backend_port, frontend_url = \
            self._launch_web_ui(args)

        # 等后端就绪再登记，避免其它链路探测到"半启动"实例而误清登记
        self._wait_for_port_ready(backend_port)

        # 登记实例，供 donkey drive / launcher / TUI 等链路复用
        my_pid = os.getpid()
        write_instance(backend_port, frontend_port, pid=my_pid)

        if args.open:
            self._open_browser_when_frontend_ready(frontend_port, frontend_url)

        stop_requested = {'value': False}

        def _handle_stop_signal(_signum, _frame):
            stop_requested['value'] = True

        prev_sigint = signal.getsignal(signal.SIGINT)
        prev_sigterm = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGINT, _handle_stop_signal)
        signal.signal(signal.SIGTERM, _handle_stop_signal)

        try:
            self._supervise_processes(
                [(name, proc) for name, proc in
                 [('前端', frontend_proc), ('后端', backend_proc)] if proc is not None],
                stop_requested,
            )
        finally:
            signal.signal(signal.SIGINT, prev_sigint)
            signal.signal(signal.SIGTERM, prev_sigterm)
            self._terminate_process(frontend_proc)
            self._terminate_process(backend_proc)
            # 仅当登记仍属于本进程时清除，避免误删他人后来的登记
            remove_instance(only_pid=my_pid)

    def _launch_web_ui(self, args):
        """解析 web_ui 路径、检查依赖、选择端口，并拉起前端+后端子进程。

        供 `donkey web` 与 `donkey drive` 共用。返回
        (frontend_proc, backend_proc, frontend_port, backend_port, frontend_url)。
        """
        web_ui_path = self._resolve_web_ui_path(args.path)
        frontend_path = os.path.join(web_ui_path, 'frontend')
        backend_path = os.path.join(web_ui_path, 'backend')

        if not os.path.isdir(frontend_path):
            raise SystemExit(f'未找到前端目录: {frontend_path}')
        if not os.path.isdir(backend_path):
            raise SystemExit(f'未找到后端目录: {backend_path}')

        if args.install_deps:
            InstallWebUI()._install_dependencies(web_ui_path, frontend_path, backend_path)
        else:
            self._check_dependencies_or_warn(frontend_path)

        backend_port = self._choose_available_port(args.backend_host, args.backend_port)
        if backend_port != args.backend_port:
            print(f'后端端口 {args.backend_port} 已被占用，已切换到 {backend_port}')

        # 前端端口仅开发模式需要（Vite 独立监听）；生产模式由后端托管 SPA，
        # frontend_port 即 backend_port，无需单独选择（#135）。
        frontend_port = args.frontend_port
        if args.dev:
            frontend_bind_host = '0.0.0.0'
            frontend_port = self._choose_available_port(frontend_bind_host, args.frontend_port)
            if frontend_port != args.frontend_port:
                print(f'前端端口 {args.frontend_port} 已被占用，已切换到 {frontend_port}')

        npm_exe = shutil.which('npm')
        if not npm_exe:
            raise SystemExit(
                '找不到 npm 命令。Web UI 前端（Vite/React）需要 Node.js/npm，'
                '这无法通过 pip 安装。\n'
                '请先系统级安装 Node.js，例如:\n'
                '  conda install -c conda-forge nodejs\n'
                '  或参考 https://nodejs.org/ 下载安装\n'
                '安装完成后运行: donkey installweb --path "{}"\n'
                '然后再启动: donkey web'.format(web_ui_path)
            )

        popen_kwargs = {}
        if os.name == 'nt':
            # On Windows, use shell=True to handle .cmd files and avoid FileNotFoundError
            # and creationflags to manage process groups if needed.
            popen_kwargs['shell'] = True
        else:
            popen_kwargs['start_new_session'] = True

        backend_env = os.environ.copy()
        if args.debug:
            backend_env["DRIVE_WEB_DEBUG"] = "1"

        if args.dev:
            # 开发模式：Vite dev 服务器提供前端（HMR 热更新），后端仅作 API。
            # dev 模式跑的是未优化代码 + React dev 运行时，页面切换明显慢，
            # 只适合前端开发调试，不适合日常使用（#135）。
            frontend_cmd = [npm_exe, 'run', 'dev', '--', '--host', '--port', str(frontend_port)]
            backend_cmd = [
                sys.executable, '-m', 'uvicorn', 'main:app',
                '--host', str(args.backend_host),
                '--port', str(backend_port),
                '--reload',
                '--log-level', 'debug' if args.debug else 'warning',
            ]

            print(f'Web UI 路径: {web_ui_path}')
            frontend_url = self._build_frontend_url(frontend_port, args.route if args.open else None)
            print(f'Web UI:  http://localhost:{backend_port}/')
            print(f'API 文档: http://localhost:{backend_port}/docs')
            print(f'开发模式: http://localhost:{frontend_port}/ (Vite HMR 热更新)')
            if args.open:
                print(f'将打开: {frontend_url}')
            print('按 Ctrl+C 停止前后端')

            frontend_env = os.environ.copy()
            # 前端使用相对路径 /api，由 Vite 代理转发到后端。
            # 必须显式指向 --backend-port 选定的端口，否则 Vite 用默认的 8000，
            # 当后端不在 8000 时浏览器 /api 请求会 ECONNREFUSED。
            frontend_env['VITE_API_PROXY_TARGET'] = f'http://127.0.0.1:{backend_port}'

            backend_proc = subprocess.Popen(backend_cmd, cwd=backend_path, env=backend_env, **popen_kwargs)
            frontend_proc = subprocess.Popen(frontend_cmd, cwd=frontend_path, env=frontend_env, **popen_kwargs)
            return frontend_proc, backend_proc, frontend_port, backend_port, frontend_url

        # 生产模式（默认）：前端构建为 dist 静态文件，由后端 uvicorn 直接托管，
        # 不再起 Vite dev 服务器。前端与 API 同源（同一端口），导航切换速度
        # 是 dev 模式的约 10 倍（实测 dev ~400-550ms vs 生产 ~43-63ms，#135）。
        if self._frontend_needs_build(frontend_path):
            print('正在构建前端生产包（首次启动或源码已更新，约 10-60 秒）...')
            build_result = subprocess.run(
                [npm_exe, 'run', 'build'],
                cwd=frontend_path,
                env=os.environ.copy(),
            )
            if build_result.returncode != 0 or not os.path.isfile(
                os.path.join(frontend_path, 'dist', 'index.html')
            ):
                raise SystemExit('前端生产构建失败，无法启动生产模式 Web UI')

        backend_cmd = [
            sys.executable, '-m', 'uvicorn', 'main:app',
            '--host', str(args.backend_host),
            '--port', str(backend_port),
            '--log-level', 'debug' if args.debug else 'warning',
        ]

        # SPA 由后端托管：前端端口即后端端口（launcher/TUI 跳转与实例登记
        # 均以 frontend_port 为准，保持复用链路兼容）。
        frontend_port = backend_port
        frontend_proc = None
        frontend_url = self._build_frontend_url(frontend_port, args.route if args.open else None)

        print(f'Web UI 路径: {web_ui_path}')
        print(f'Web UI:  http://localhost:{backend_port}/')
        print(f'API 文档: http://localhost:{backend_port}/docs')
        if args.open:
            print(f'将打开: {frontend_url}')
        print('按 Ctrl+C 停止')

        backend_proc = subprocess.Popen(backend_cmd, cwd=backend_path, env=backend_env, **popen_kwargs)

        return frontend_proc, backend_proc, frontend_port, backend_port, frontend_url

    def _frontend_needs_build(self, frontend_path):
        """判断前端是否需要重新构建：dist 缺失，或源码比 dist/index.html 新。"""
        dist_index = os.path.join(frontend_path, 'dist', 'index.html')
        if not os.path.isfile(dist_index):
            return True
        dist_mtime = os.path.getmtime(dist_index)
        checked_roots = ['src', 'public']
        checked_files = [
            'index.html', 'vite.config.ts', 'package.json', 'tsconfig.json',
            'tsconfig.app.json', 'tsconfig.node.json', 'tailwind.config.js',
            'postcss.config.js',
        ]
        for name in checked_files:
            p = os.path.join(frontend_path, name)
            if os.path.isfile(p) and os.path.getmtime(p) > dist_mtime:
                return True
        for root_name in checked_roots:
            root = os.path.join(frontend_path, root_name)
            if not os.path.isdir(root):
                continue
            for dirpath, _dirnames, filenames in os.walk(root):
                if 'node_modules' in dirpath:
                    continue
                for filename in filenames:
                    p = os.path.join(dirpath, filename)
                    if os.path.getmtime(p) > dist_mtime:
                        return True
        return False

    def _supervise_processes(self, named_procs, stop_requested):
        """监督子进程：收到停止信号或任一进程退出时，终止全部并以 SystemExit 退出。

        named_procs: [(名称, proc), ...]，按顺序轮询。
        """
        while True:
            if stop_requested['value']:
                raise SystemExit(0)
            for name, proc in named_procs:
                rc = proc.poll()
                if rc is not None:
                    for _, other in named_procs:
                        self._terminate_process(other)
                    raise SystemExit(f'{name}进程已退出，返回码: {rc}')
            time.sleep(0.25)

    def _build_frontend_url(self, frontend_port, route=None):
        if not route or route == '/':
            return f'http://localhost:{frontend_port}/'
        normalized_route = route if str(route).startswith('/') else f'/{route}'
        return f'http://localhost:{frontend_port}/#{normalized_route}'

    def _wait_for_port_ready(self, port, timeout=30.0):
        """轮询本机端口直至可连接或超时。返回是否就绪。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=0.5):
                    return True
            except OSError:
                time.sleep(0.2)
        return False

    def _open_browser_when_frontend_ready(self, frontend_port, frontend_url, timeout=30.0):
        """等前端端口开始监听后再打开浏览器。

        Vite 启动需要数秒；若在其就绪前打开浏览器，页面会显示无法连接，
        且浏览器不会自动恢复，用户只能手动刷新。超时仍打开（由用户自行刷新）。
        """
        if not self._wait_for_port_ready(frontend_port, timeout):
            print(f'警告: 前端端口 {frontend_port} 在 {timeout:.0f}s 内未就绪，仍将打开浏览器')
        webbrowser.open(frontend_url)

    def _choose_available_port(self, host, preferred_port, max_tries=50):
        port = int(preferred_port)
        for _ in range(max_tries):
            if self._is_port_available(host, port):
                return port
            port += 1
        raise SystemExit(f'无法找到可用端口 (host={host}, 起始端口={preferred_port})')

    def _is_port_available(self, host, port):
        try:
            addr_infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except Exception:
            addr_infos = [(socket.AF_INET, socket.SOCK_STREAM, 0, '', (host, port))]

        for family, socktype, proto, _, sockaddr in addr_infos:
            sock = None
            try:
                sock = socket.socket(family, socktype, proto)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(sockaddr)
                return True
            except OSError:
                continue
            finally:
                if sock is not None:
                    try:
                        sock.close()
                    except Exception:
                        pass

        return False

    def _resolve_web_ui_path(self, path):
        normalized = os.path.expanduser(str(path)).replace('\\', os.sep)
        normalized = os.path.normpath(normalized)
        if self._is_web_ui_dir(normalized):
            return normalized

        cwd = os.getcwd()
        candidate = cwd
        while True:
            direct = os.path.join(candidate, 'web_ui')
            if self._is_web_ui_dir(direct):
                return direct
            if self._is_web_ui_dir(candidate):
                return candidate
            parent = os.path.dirname(candidate)
            if parent == candidate:
                break
            candidate = parent

        raise SystemExit(
            f'未找到 web_ui 目录。请使用 --path 指定，例如: donkey web --path "{normalized}"'
        )

    def _is_web_ui_dir(self, path):
        return (
            os.path.isdir(path)
            and os.path.isdir(os.path.join(path, 'frontend'))
            and os.path.isdir(os.path.join(path, 'backend'))
        )

    def _check_dependencies_or_warn(self, frontend_path):
        """
        Lightweight pre-flight check used by `donkey web` when `--install-deps`
        is NOT passed. Prints a one-line hint per missing dep group so the user
        can quickly recover with `donkey installweb` (or `pip install -e .[fastapi-backend]`).
        Never raises — the existing process-spawn path will produce a clearer
        error if a dep is actually required.
        """
        missing = []
        if not _BACKEND_DEPS_OK:
            missing.append('backend (pip install -e .[fastapi-backend])')
        if shutil.which('npm') is None:
            missing.append('node/npm runtime (must be installed system-wide, not via pip)')
        elif not os.path.isdir(os.path.join(frontend_path, 'node_modules')):
            missing.append('frontend (donkey installweb)')
        if missing:
            print('检测到 Web UI 依赖可能不完整: ' + ', '.join(missing))
            if shutil.which('npm') is None:
                print('  → 请先安装 Node.js（系统级），例如:')
                print('     conda install -c conda-forge nodejs')
                print('     或参考 https://nodejs.org/ 下载安装')
            else:
                print('  → 自动安装: donkey web --install-deps')
                print('  → 手动安装: donkey installweb --path "{}"'.format(
                    os.path.dirname(frontend_path)
                ))

    def _terminate_process(self, proc):
        if proc is None:
            return
        if proc.poll() is not None:
            return
        if os.name == 'posix':
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except Exception:
                proc.terminate()
        else:
            proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            if os.name == 'posix':
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except Exception:
                    proc.kill()
            else:
                proc.kill()
            proc.wait(timeout=5)


class Drive(Web):
    """`donkey drive` — 一键拉起 Web UI 前后端 + 本机 manage.py drive。

    在 `donkey web` 的基础上额外启动本机 Vehicle（manage.py drive），并自动注入
    DRIVE_API_SERVER_URL，使车端以 role=car 连回 Web UI 后端的 /api/drive/ws。
    浏览器访问 http://localhost:<backend-port>/#/drive 即可控制真实小车。
    """

    def parse_args(self, args):
        parser = argparse.ArgumentParser(prog='drive', usage='%(prog)s [options]')
        parser.add_argument('--path', default='/home/dkc/projects/donkeycar/web_ui',
                            help='web_ui 根目录路径 (默认: /home/dkc/projects/donkeycar/web_ui)')
        parser.add_argument('--car', default=None,
                            help='车目录路径（须含 manage.py，默认: 当前目录）')
        parser.add_argument('--model', default=None,
                            help='推理模型路径，透传给 manage.py drive --model')
        parser.add_argument('--type', default=None,
                            help='模型类型 (linear|categorical)，透传给 manage.py drive --type')
        parser.add_argument('--js', action='store_true',
                            help='使用物理摇杆，透传给 manage.py drive --js')
        parser.add_argument('--frontend-port', type=int, default=5188,
                            help='前端端口 (默认: 5188)')
        parser.add_argument('--backend-port', type=int, default=8000,
                            help='后端端口 (默认: 8000)')
        parser.add_argument('--backend-host', default='0.0.0.0',
                            help='后端监听地址 (默认: 0.0.0.0)')
        parser.add_argument('--install-deps', action='store_true',
                            help='启动前自动安装缺失的前后端依赖 (等价于先运行 `donkey installweb`)')
        parser.add_argument('--open', action='store_true',
                            help='启动后自动打开浏览器')
        parser.add_argument('--route', default='/drive',
                            help='自动打开的前端路由 (默认: /drive)')
        parser.add_argument('--dev', action='store_true',
                            help='开发模式：用 Vite dev 服务器起前端（HMR 热更新，页面切换明显慢于生产构建）。'
                                 '默认为生产模式：构建 dist 后由后端静态托管（#135）')
        parser.add_argument('--debug', action='store_true',
                            help='启用 DEBUG 日志模式 (默认仅输出 WARNING 及以上级别日志)')
        return parser.parse_args(args)

    def run(self, args):
        args = self.parse_args(args)
        car_path = self._resolve_car_path(args.car)

        # 只杀上一次的车进程（manage.py drive）释放硬件，web 前后端保留复用（issue #127）
        _kill_previous_drive_processes()

        # 已有存活的 Web UI 实例则复用，只启动车进程
        inst = find_live_instance()
        my_pid = os.getpid()
        owns_instance = False
        frontend_proc = backend_proc = None

        if inst:
            frontend_port = inst['frontend_port']
            backend_port = inst['backend_port']
            print(f'检测到运行中的 Web UI 实例 '
                  f'(backend=:{backend_port} frontend=:{frontend_port})，'
                  '复用已有实例，只启动车辆进程')
        else:
            frontend_proc, backend_proc, frontend_port, backend_port, frontend_url = \
                self._launch_web_ui(args)

            # 等待后端就绪后再启动车辆，避免车端 WS 先于后端启动导致连接失败重试风暴
            if not self._wait_for_backend_ready(backend_port):
                self._terminate_process(frontend_proc)
                self._terminate_process(backend_proc)
                raise SystemExit(f'后端端口 {backend_port} 未在超时内就绪，已终止 Web UI')

            # 登记实例，供 donkey web / launcher / TUI 等链路复用
            write_instance(backend_port, frontend_port, pid=my_pid)
            owns_instance = True

        car_cmd = self._build_car_command(args)
        car_env = self._build_car_env(backend_port)

        popen_kwargs = {}
        if os.name == 'nt':
            popen_kwargs['shell'] = True
        else:
            popen_kwargs['start_new_session'] = True

        print(f'车辆目录: {car_path}')
        print(f'车辆进程: {" ".join(car_cmd)}')
        car_proc = subprocess.Popen(
            car_cmd, cwd=car_path, env=car_env,
            stdin=subprocess.DEVNULL, **popen_kwargs,
        )

        # 记录进程 PID，供下次启动时清理；复用实例时 web 进程不属于本进程管
        if frontend_proc is not None:
            write_drive_pids([frontend_proc.pid, backend_proc.pid, car_proc.pid])
        else:
            write_drive_pids([car_proc.pid])

        if args.open:
            frontend_url = self._build_frontend_url(frontend_port, args.route)
            self._open_browser_when_frontend_ready(frontend_port, frontend_url)
        print('按 Ctrl+C 停止前端、后端与车辆进程')

        stop_requested = {'value': False}

        def _handle_stop_signal(_signum, _frame):
            stop_requested['value'] = True

        prev_sigint = signal.getsignal(signal.SIGINT)
        prev_sigterm = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGINT, _handle_stop_signal)
        signal.signal(signal.SIGTERM, _handle_stop_signal)

        supervised = [('车辆', car_proc)]
        if frontend_proc is not None:
            supervised = [('前端', frontend_proc), ('后端', backend_proc)] + supervised
        try:
            self._supervise_processes(supervised, stop_requested)
        finally:
            signal.signal(signal.SIGINT, prev_sigint)
            signal.signal(signal.SIGTERM, prev_sigterm)
            if frontend_proc is not None:
                self._terminate_process(frontend_proc)
                self._terminate_process(backend_proc)
            self._terminate_process(car_proc)
            remove_drive_pid_file()
            if owns_instance:
                # 仅当登记仍属于本进程时清除，避免误删他人后来的登记
                remove_instance(only_pid=my_pid)

    # ------------------------------------------------------------------
    # 车辆子进程构造（纯逻辑，便于单测）
    # ------------------------------------------------------------------

    def _resolve_car_path(self, car_arg):
        car_path = os.path.abspath(os.path.expanduser(car_arg)) if car_arg else os.getcwd()
        if not os.path.isfile(os.path.join(car_path, 'manage.py')):
            raise SystemExit(
                f'车目录未找到 manage.py: {car_path}\n'
                '请通过 --car 指定包含 manage.py 的车目录，或在车目录中运行 donkey drive。'
            )
        return car_path

    def _build_car_command(self, args):
        """构造 manage.py drive 命令行，透传 --model/--type/--js。"""
        cmd = [sys.executable, 'manage.py', 'drive']
        if args.model:
            cmd.extend(['--model', args.model])
        if args.type:
            cmd.extend(['--type', args.type])
        if args.js:
            cmd.append('--js')
        return cmd

    def _build_car_env(self, backend_port):
        """构造车端子进程环境，注入 DRIVE_API_SERVER_URL 指向本机后端。"""
        env = os.environ.copy()
        env['DRIVE_API_SERVER_URL'] = f'ws://127.0.0.1:{backend_port}/api/drive/ws'
        return env

    def _wait_for_backend_ready(self, backend_port, timeout=30.0):
        """轮询后端端口直至可连或超时。返回是否就绪。"""
        return self._wait_for_port_ready(backend_port, timeout)


class InstallWebUI(BaseCommand):
    """
    `donkey installweb` — install / repair Web UI dependencies.

    Backend (Python): checks for fastapi/uvicorn/python-multipart and runs
        `pip install -e .[fastapi-backend]` (or equivalent) into the active interpreter
        if anything is missing. The user can skip this with `--no-backend`.

    Frontend (Node.js): runs `npm install` in `web_ui/frontend` (or `--no-frontend`
        to skip). Requires `node` and `npm` on PATH.

    The command is idempotent: re-running is safe and will only install what
    is actually missing.
    """

    def parse_args(self, args):
        parser = argparse.ArgumentParser(
            prog='installweb',
            usage='%(prog)s [options]',
            description='Install/repair Web UI backend (Python) and frontend (Node) dependencies.'
        )
        parser.add_argument(
            '--path', default='/home/dkc/projects/donkeycar/web_ui',
            help='web_ui 根目录路径 (默认: /home/dkc/projects/donkeycar/web_ui)',
        )
        parser.add_argument(
            '--no-backend', action='store_true',
            help='跳过 Python 后端依赖检查与安装',
        )
        parser.add_argument(
            '--no-frontend', action='store_true',
            help='跳过前端 npm install',
        )
        return parser.parse_args(args)

    def run(self, args):
        args = self.parse_args(args)
        web_ui_path = Web()._resolve_web_ui_path(args.path)
        frontend_path = os.path.join(web_ui_path, 'frontend')
        backend_path = os.path.join(web_ui_path, 'backend')
        if not os.path.isdir(frontend_path):
            raise SystemExit(f'未找到前端目录: {frontend_path}')
        if not os.path.isdir(backend_path):
            raise SystemExit(f'未找到后端目录: {backend_path}')
        self._install_dependencies(web_ui_path, frontend_path, backend_path,
                                  skip_backend=args.no_backend,
                                  skip_frontend=args.no_frontend)

    # --- core routine, also reused by `donkey web --install-deps` ---
    def _install_dependencies(self, web_ui_path, frontend_path, backend_path,
                              skip_backend=False, skip_frontend=False):
        print(f'Web UI 路径: {web_ui_path}')

        backend_ok = True
        if not skip_backend:
            backend_ok = self._ensure_backend_deps(web_ui_path, backend_path)
        else:
            print('跳过 Python 后端依赖安装 (--no-backend)')

        frontend_ok = True
        if not skip_frontend:
            frontend_ok = self._ensure_frontend_deps(frontend_path)
        else:
            print('跳过前端 npm install (--no-frontend)')

        print('--- Web UI 依赖检查完成 ---')
        print(f'  后端: {"OK" if backend_ok else "FAILED"}')
        print(f'  前端: {"OK" if frontend_ok else "FAILED"}')
        if not (backend_ok and frontend_ok):
            missing = []
            if not backend_ok:
                missing.append('Python 后端 (pip install -e .[fastapi-backend])')
            if not frontend_ok:
                missing.append('前端 (npm install)')
            raise SystemExit(
                '依赖安装未完成: ' + ', '.join(missing)
                + '\n请根据上方错误信息手动重试后，再运行 `donkey web` 启动。'
            )

    def _ensure_backend_deps(self, web_ui_path, backend_path):
        """Verify / install Python backend deps (fastapi, uvicorn, python-multipart)."""
        global _BACKEND_DEPS_OK
        missing = [m for m in _WEBUI_BACKEND_MODULES
                   if importlib.util.find_spec(m) is None]
        if not missing:
            print(f'后端依赖已就绪: {", ".join(_WEBUI_BACKEND_MODULES)}')
            return True

        print(f'后端缺失依赖: {", ".join(missing)}')
        # Prefer the requirements file shipped with the repo for the canonical
        # pinned set; fall back to the [fastapi-backend] extra if it is unreachable.
        req_file = os.path.join(backend_path, 'requirements.txt')
        if os.path.isfile(req_file):
            cmd = [sys.executable, '-m', 'pip', 'install', '-r', req_file]
            print('  → 执行: ' + ' '.join(cmd))
        else:
            cmd = [sys.executable, '-m', 'pip', 'install', '-e', f'{web_ui_path or "."}[fastapi-backend]']
            print(f'  未找到 {req_file}，回退到: ' + ' '.join(cmd))

        try:
            subprocess.check_call(cmd)
        except subprocess.CalledProcessError as exc:
            print(f'  pip install 失败，返回码: {exc.returncode}')
            return False

        # Refresh the cached flag now that we've installed.
        _BACKEND_DEPS_OK = all(
            importlib.util.find_spec(name) is not None
            for name in _WEBUI_BACKEND_MODULES
        )
        if not _BACKEND_DEPS_OK:
            still_missing = [m for m in _WEBUI_BACKEND_MODULES
                             if importlib.util.find_spec(m) is None]
            print(f'  pip install 报告成功但仍缺失: {", ".join(still_missing)}')
            return False
        return True

    def _ensure_frontend_deps(self, frontend_path):
        """Run `npm install` in the frontend directory if node_modules is missing."""
        node_modules = os.path.join(frontend_path, 'node_modules')
        package_json = os.path.join(frontend_path, 'package.json')
        if not os.path.isfile(package_json):
            raise SystemExit(f'未找到 package.json: {package_json}')

        npm_exe = shutil.which('npm')
        if npm_exe is None:
            print('  未在 PATH 中找到 npm，请先安装 Node.js (https://nodejs.org)')
            return False

        if os.path.isdir(node_modules):
            # Cheap sanity check: vite must be resolvable.
            vite_bin = os.path.join(node_modules, '.bin', 'vite')
            if os.path.isfile(vite_bin) or os.path.isfile(vite_bin + '.cmd'):
                print(f'前端依赖已就绪: {node_modules}')
                return True
            print(f'  node_modules 存在但缺少 vite，将重新执行 npm install')

        cmd = [npm_exe, 'install']
        print('  → 执行: ' + ' '.join(cmd) + f'  (cwd={frontend_path})')
        try:
            subprocess.check_call(cmd, cwd=frontend_path)
        except subprocess.CalledProcessError as exc:
            print(f'  npm install 失败，返回码: {exc.returncode}')
            return False

        if not os.path.isdir(node_modules):
            print(f'  npm install 报告成功但未生成: {node_modules}')
            return False
        return True


def execute_from_command_line():
    """
    This is the function linked to the "donkey" terminal command.
    """
    commands = {
        'createcar': CreateCar,
        'findcar': FindCar,
        'calibrate': CalibrateCar,
        'tubplot': ShowPredictionPlots,
        'tubhist': ShowHistogram,
        'evaluate': Evaluate,
        'makemovie': MakeMovieShell,
        'createjs': CreateJoystick,
        'cnnactivations': ShowCnnActivations,
        'update': UpdateCar,
        'train': Train,
        'models': ModelDatabase,
        'ui': Gui,
        'tui': Tui,
        'web': Web,
        'drive': Drive,
        'installweb': InstallWebUI,
    }

    args = sys.argv[:]

    if len(args) > 1 and args[1] in commands.keys():
        command = commands[args[1]]
        c = command()
        c.run(args[2:])
    elif len(args) == 1:
        # Default to TUI
        c = Tui()
        c.run([])
    else:
        dk.utils.eprint('DonkeyDrifter CLI')
        dk.utils.eprint('Usage: The available commands are:')
        dk.utils.eprint(list(commands.keys()))


if __name__ == "__main__":
    execute_from_command_line()