#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Jun 24 20:10:44 2017
@author: wroscoe
remotes.py
The client and web server needed to control a car remotely.
"""


import os
import json
import logging
import time
import asyncio
from pathlib import Path

import requests
from tornado.ioloop import IOLoop
from tornado.web import Application, RedirectHandler, StaticFileHandler, \
    RequestHandler
from tornado.httpserver import HTTPServer
import tornado.gen
import tornado.websocket
from socket import gethostname

from ... import utils

logger = logging.getLogger(__name__)


class RemoteWebServer():
    '''
    A controller that repeatedly polls a remote webserver and expects
    the response to be angle, throttle and drive mode.
    '''

    def __init__(self, remote_url, connection_timeout=.25):

        self.control_url = remote_url
        self.time = 0.
        self.angle = 0.
        self.throttle = 0.
        self.mode = 'user'
        self.mode_latch = None
        self.recording = False
        # use one session for all requests
        self.session = requests.Session()

    def update(self):
        '''
        Loop to run in separate thread the updates angle, throttle and
        drive mode.
        '''

        while True:
            # get latest value from server
            self.angle, self.throttle, self.mode, self.recording = self.run()

    def run_threaded(self):
        '''
        Return the last state given from the remote server.
        '''
        return self.angle, self.throttle, self.mode, self.recording

    def run(self):
        '''
        Posts current car sensor data to webserver and returns
        angle and throttle recommendations.
        '''

        data = {}
        response = None
        while response is None:
            try:
                response = self.session.post(self.control_url,
                                             files={'json': json.dumps(data)},
                                             timeout=0.25)

            except requests.exceptions.ReadTimeout as err:
                print("\n Request took too long. Retrying")
                # Lower throttle to prevent runaways.
                return self.angle, self.throttle * .8, None

            except requests.ConnectionError as err:
                # try to reconnect every 3 seconds
                print("\n Vehicle could not connect to server. Make sure you've " +
                    "started your server and you're referencing the right port.")
                time.sleep(3)

        data = json.loads(response.text)
        angle = float(data['angle'])
        throttle = float(data['throttle'])
        drive_mode = str(data['drive_mode'])
        recording = bool(data['recording'])

        return angle, throttle, drive_mode, recording

    def shutdown(self):
        pass


class LocalWebController(tornado.web.Application):

    def __init__(self, port=8887, mode='user'):
        """
        Create and publish variables needed on many of
        the web handlers.
        """
        logger.info('Starting Donkey Server...')

        this_dir = os.path.dirname(os.path.realpath(__file__))
        self.static_file_path = os.path.join(this_dir, 'templates', 'static')
        self.angle = 0.0
        self.throttle = 0.0
        self.mode = mode
        self.mode_latch = None
        self.recording = False
        self.recording_latch = None
        self.buttons = {}  # latched button values for processing

        self.port = port

        self.num_records = 0
        self.wsclients = []
        self.loop = None
        
        # 初始化参数管理器
        self.params_manager = ParamsManager()
        logger.info(f"Parameters manager initialized. Config file: {self.params_manager.config_file}")


        handlers = [
            (r"/", RedirectHandler, dict(url="/drive")),
            (r"/drive", DriveAPI),
            (r"/wsDrive", WebSocketDriveAPI),
            (r"/wsCalibrate", WebSocketCalibrateAPI),
            (r"/calibrate", CalibrateHandler),
            (r"/video", VideoAPI),
            (r"/wsTest", WsTest),
            (r"/api/get_params", GetParamsHandler),
            (r"/api/save_params", SaveParamsHandler),

            (r"/static/(.*)", StaticFileHandler,
             {"path": self.static_file_path}),
        ]

        settings = {'debug': True}
        super().__init__(handlers, **settings)
        url = f"http://localhost:{port}"
        logger.info(f"You can now go to {url} to drive your car.")
        
        # Automatically open browser
        import webbrowser
        try:
            webbrowser.open(url)
        except Exception as e:
            logger.warning(f"Failed to open browser automatically: {e}")

    def update(self):
        """ Start the tornado webserver. """
        asyncio.set_event_loop(asyncio.new_event_loop())
        self.listen(self.port)
        self.loop = IOLoop.instance()
        self.loop.start()

    def update_wsclients(self, data):
        if data:
            for wsclient in self.wsclients:
                try:
                    data_str = json.dumps(data)
                    logger.debug(f"Updating web client: {data_str}")
                    wsclient.write_message(data_str)
                except Exception as e:
                    logger.warning("Error writing websocket message",
                                   exc_info=e)
                    pass

    def run_threaded(self, img_arr=None, num_records=0, mode=None, recording=None):
        """
        :param img_arr: current camera image or None
        :param num_records: current number of data records
        :param mode: default user/mode
        :param recording: default recording mode
        """
        self.img_arr = img_arr
        self.num_records = num_records

        #
        # enforce defaults if they are not none.
        #
        changes = {}
        if mode is not None and self.mode != mode:
            self.mode = mode
            changes["driveMode"] = self.mode
        if self.mode_latch is not None:
            self.mode = self.mode_latch
            self.mode_latch = None
            changes["driveMode"] = self.mode
        if recording is not None and self.recording != recording:
            self.recording = recording
            changes["recording"] = self.recording
        if self.recording_latch is not None:
            self.recording = self.recording_latch;
            self.recording_latch = None;
            changes["recording"] = self.recording;

        # Send record count to websocket clients
        if (self.num_records is not None and self.recording is True):
            if self.num_records % 10 == 0:
                changes['num_records'] = self.num_records

        #
        # get latched button presses then clear button presses
        # Next iteration will clear press in memory
        #
        buttons = self.buttons
        self.buttons = {}
        for button, pressed in buttons.items():
            if pressed:
                self.buttons[button] = False

        # if there were changes, then send to web client
        if changes and self.loop is not None:
            logger.debug(str(changes))
            self.loop.add_callback(lambda: self.update_wsclients(changes))

        return self.angle, self.throttle, self.mode, self.recording, buttons

    def run(self, img_arr=None, num_records=0, mode=None, recording=None):
        return self.run_threaded(img_arr, num_records, mode, recording)

    def shutdown(self):
        pass


class DriveAPI(RequestHandler):

    def get(self):
        data = {}
        self.render("templates/vehicle.html", **data)

    def post(self):
        '''
        Receive post requests as user changes the angle
        and throttle of the vehicle on a the index webpage
        '''
        data = tornado.escape.json_decode(self.request.body)

        if data.get('angle') is not None:
            self.application.angle = data['angle']
        if data.get('throttle') is not None:
            self.application.throttle = data['throttle']
        if data.get('drive_mode') is not None:
            self.application.mode = data['drive_mode']
        if data.get('recording') is not None:
            self.application.recording = data['recording']
        if data.get('buttons') is not None:
            latch_buttons(self.application.buttons, data['buttons'])


class WsTest(RequestHandler):
    def get(self):
        data = {}
        self.render("templates/wsTest.html", **data)


class ParamsManager:
    """
    参数持久化管理器 - 负责保存和加载驾驶控制参数
    """
    def __init__(self, config_dir=None):
        """
        初始化参数管理器
        :param config_dir: 配置文件目录，默认为 ~/mycar/
        """
        if config_dir is None:
            config_dir = os.path.expanduser("~/mycar/")
        
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.config_dir / "drive_params.json"
        
        # 默认参数
        self.default_params = {
            'version': '2.0',
            'params': {
                'pid': {'kp': 0.8, 'ki': 0.0, 'kd': 0.05},
                'recenterRate': 0.35,
                'steerRate': 1.2,
                'accelRate': 1.0,
                'brakeRate': 1.2
            }
        }
    
    def validate_params(self, params):
        """验证参数格式和数值范围"""
        if not isinstance(params, dict):
            return False
        
        pid = params.get('pid', {})
        if not all(isinstance(pid.get(k), (int, float)) for k in ['kp', 'ki', 'kd']):
            return False
        
        if not (0 <= pid.get('kp', -1) <= 3):
            return False
        if not (0 <= pid.get('ki', -1) <= 1):
            return False
        if not (0 <= pid.get('kd', -1) <= 0.1):
            return False
        
        for key in ['recenterRate', 'steerRate', 'accelRate', 'brakeRate']:
            val = params.get(key, -1)
            if not isinstance(val, (int, float)) or val < 0 or val > 3:
                return False
        
        return True
    
    def load(self):
        """从文件加载参数"""
        try:
            if not self.config_file.exists():
                logger.info("No saved parameters found, using defaults")
                return self.default_params['params']
            
            with open(self.config_file, 'r') as f:
                data = json.load(f)
            
            if not self.validate_params(data.get('params', {})):
                logger.error("Loaded parameters validation failed, using defaults")
                return self.default_params['params']
            
            logger.info(f"Parameters loaded from {self.config_file}")
            return data['params']
        
        except Exception as e:
            logger.error(f"Failed to load parameters: {e}")
            return self.default_params['params']
    
    def save(self, params):
        """保存参数到文件"""
        try:
            if not self.validate_params(params):
                raise ValueError("Parameters validation failed")
            
            data = {
                'version': '2.0',
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
                'params': params
            }
            
            # 写入临时文件，然后原子性重命名（防止写入过程中崩溃）
            temp_file = self.config_file.with_suffix('.json.tmp')
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            temp_file.replace(self.config_file)
            logger.info(f"Parameters saved to {self.config_file}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to save parameters: {e}")
            return False


class GetParamsHandler(RequestHandler):
    """获取驾驶参数的 HTTP API"""
    async def get(self):
        try:
            params_manager = self.application.params_manager
            params = params_manager.load()
            self.set_header('Content-Type', 'application/json')
            self.write({
                'success': True,
                'params': params,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            })
        except Exception as e:
            logger.error(f"Error in GetParamsHandler: {e}")
            self.set_status(500)
            self.write({
                'success': False,
                'error': str(e)
            })


class SaveParamsHandler(RequestHandler):
    """保存驾驶参数的 HTTP API"""
    async def post(self):
        try:
            data = json.loads(self.request.body)
            params = data.get('params')
            
            if not params:
                raise ValueError("Missing 'params' field")
            
            params_manager = self.application.params_manager
            success = params_manager.save(params)
            
            self.set_header('Content-Type', 'application/json')
            if success:
                self.write({
                    'success': True,
                    'message': 'Parameters saved successfully',
                    'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
                })
            else:
                self.set_status(500)
                self.write({
                    'success': False,
                    'error': 'Failed to save parameters'
                })
        
        except Exception as e:
            logger.error(f"Error in SaveParamsHandler: {e}")
            self.set_status(500)
            self.write({
                'success': False,
                'error': str(e)
            })


class CalibrateHandler(RequestHandler):
    """ Serves the calibration web page"""
    async def get(self):
        await self.render("templates/calibrate.html")


def latch_buttons(buttons, pushes):
    """
    Latch button pushes
    buttons: the latched values
    pushes: the update value
    """
    if pushes is not None:
        #
        # we got button pushes.
        # - we latch the pushed buttons so we can process the push
        # - after it is processed we clear it
        #
        for button in pushes:
            # if pushed, then latch it
            if pushes[button]:
                buttons[button] = True


class WebSocketDriveAPI(tornado.websocket.WebSocketHandler):
    def check_origin(self, origin):
        return True

    def open(self):
        logger.info("New client connected")
        self.application.wsclients.append(self)

    def on_message(self, message):
        data = json.loads(message)
        
        # 处理参数保存请求
        if data.get('msg_type') == 'save_params':
            try:
                params = data.get('params')
                if params:
                    params_manager = self.application.params_manager
                    success = params_manager.save(params)
                    logger.info(f"Parameters saved via WebSocket: {success}")
            except Exception as e:
                logger.error(f"Failed to save parameters via WebSocket: {e}")
            return
        
        # 正常的驾驶控制消息
        self.application.angle = data.get('angle', self.application.angle)
        self.application.throttle = data.get('throttle', self.application.throttle)
        if data.get('drive_mode') is not None:
            self.application.mode = data['drive_mode']
            self.application.mode_latch = self.application.mode
        if data.get('recording') is not None:
            self.application.recording = data['recording']
            self.application.recording_latch = self.application.recording
        if data.get('buttons') is not None:
            latch_buttons(self.application.buttons, data['buttons'])

    def on_close(self):
        logger.info("Client disconnected")
        self.application.wsclients.remove(self)


class WebSocketCalibrateAPI(tornado.websocket.WebSocketHandler):
    def check_origin(self, origin):
        return True

    def open(self):
        logger.info("New client connected")

    def on_message(self, message):
        logger.info(f"wsCalibrate {message}")
        data = json.loads(message)
        if 'throttle' in data:
            print(data['throttle'])
            self.application.throttle = data['throttle']

        if 'angle' in data:
            print(data['angle'])
            self.application.angle = data['angle']

        if 'config' in data:
            config = data['config']
            if self.application.drive_train_type == "PWM_STEERING_THROTTLE" \
                or self.application.drive_train_type == "I2C_SERVO":
                if 'STEERING_LEFT_PWM' in config:
                    self.application.drive_train['steering'].left_pulse = config['STEERING_LEFT_PWM']

                if 'STEERING_RIGHT_PWM' in config:
                    self.application.drive_train['steering'].right_pulse = config['STEERING_RIGHT_PWM']

                if 'THROTTLE_FORWARD_PWM' in config:
                    self.application.drive_train['throttle'].max_pulse = config['THROTTLE_FORWARD_PWM']

                if 'THROTTLE_STOPPED_PWM' in config:
                    self.application.drive_train['throttle'].zero_pulse = config['THROTTLE_STOPPED_PWM']

                if 'THROTTLE_REVERSE_PWM' in config:
                    self.application.drive_train['throttle'].min_pulse = config['THROTTLE_REVERSE_PWM']

            elif self.application.drive_train_type == "MM1":
                if ('MM1_STEERING_MID' in config) and (config['MM1_STEERING_MID'] != 0):
                        self.application.drive_train.STEERING_MID = config['MM1_STEERING_MID']
                if ('MM1_MAX_FORWARD' in config) and (config['MM1_MAX_FORWARD'] != 0):
                        self.application.drive_train.MAX_FORWARD = config['MM1_MAX_FORWARD']
                if ('MM1_MAX_REVERSE' in config) and (config['MM1_MAX_REVERSE'] != 0):
                    self.application.drive_train.MAX_REVERSE = config['MM1_MAX_REVERSE']

    def on_close(self):
        logger.info("Client disconnected")


class VideoAPI(RequestHandler):
    '''
    Serves a MJPEG of the images posted from the vehicle.
    '''

    async def get(self):
        placeholder_image = utils.load_image_sized(
                        os.path.join(self.application.static_file_path,
                                     "img_placeholder.jpg"), 160, 120, 3)

        self.set_header("Content-type",
                        "multipart/x-mixed-replace;boundary=--boundarydonotcross")

        served_image_timestamp = time.time()
        my_boundary = "--boundarydonotcross\n"
        while True:

            interval = .005
            if served_image_timestamp + interval < time.time():
                #
                # if we have an image, then use it.
                # otherwise show placeholder
                #
                if hasattr(self.application, 'img_arr') and self.application.img_arr is not None:
                    img = utils.arr_to_binary(self.application.img_arr)
                else:
                    img = utils.arr_to_binary(placeholder_image)

                self.write(my_boundary)
                self.write("Content-type: image/jpeg\r\n")
                self.write("Content-length: %s\r\n\r\n" % len(img))
                self.write(img)
                served_image_timestamp = time.time()
                try:
                    await self.flush()
                except tornado.iostream.StreamClosedError:
                    pass
            else:
                await tornado.gen.sleep(interval)


class BaseHandler(RequestHandler):
    """ Serves the FPV web page"""
    async def get(self):
        data = {}
        await self.render("templates/base_fpv.html", **data)


class WebFpv(Application):
    """
    Class for running an FPV web server that only shows the camera in real-time.
    The web page contains the camera view and auto-adjusts to the web browser
    window size. Conjecture: this picture up-scaling is performed by the
    client OS using graphics acceleration. Hence a web browser on the PC is
    faster than a pure python application based on open cv or similar.
    """

    def __init__(self, port=8890):
        self.port = port
        this_dir = os.path.dirname(os.path.realpath(__file__))
        self.static_file_path = os.path.join(this_dir, 'templates', 'static')

        """Construct and serve the tornado application."""
        handlers = [
            (r"/", BaseHandler),
            (r"/video", VideoAPI),
            (r"/static/(.*)", StaticFileHandler,
             {"path": self.static_file_path})
        ]

        settings = {'debug': True}
        self.img_arr = None
        super().__init__(handlers, **settings)
        logger.info(f"Started Web FPV server. You can now go to "
                    f"{gethostname()}.local:{self.port} to view the car camera")

    def update(self):
        """ Start the tornado webserver. """
        asyncio.set_event_loop(asyncio.new_event_loop())
        self.listen(self.port)
        IOLoop.instance().start()

    def run_threaded(self, img_arr=None):
        self.img_arr = img_arr

    def run(self, img_arr=None):
        self.img_arr = img_arr

    def shutdown(self):
        pass


