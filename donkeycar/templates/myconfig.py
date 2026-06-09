# """ 
# myconfig.py（我的配置）
# 本文件读取manage.py脚本，并在此基础上修改
# 所有配置都可以在此修改，且程序更新不会修改本文件
# """
import os
import re
import subprocess
import sys

#--------------------------For DonkeyCar 驴车实车相关配置
# 转向(控制舵机)
STEERING_PWM_CHANNEL = 0    # 转向PWM通道（默认：0）
STEERING_LEFT_PWM = -100    # 转向左PWM值（默认：-100）
STEERING_RIGHT_PWM = 100    # 转向右PWM值（默认：100）

# 油门(控制电调>>电机)
THROTTLE_PWM_CHANNEL = 1    # 油门PWM通道（默认：1）
THROTTLE_FORWARD_PWM = 100  # 最大前进油门配置（默认：100）
THROTTLE_STOPPED_PWM = 0    # 停止油门配置（默认：0）
THROTTLE_REVERSE_PWM = -100 # 最大倒车油门配置（默认：-100）

# 底盘控制器串口配置
DRIVE_TRAIN_TYPE = "ARDUINO_CONTROLLER" # 底盘驱动器类型
ARDUINO_SERIAL_PORT = "/dev/ttyS4"      # 默认串口端口（默认：/dev/ttyS4）
ARDUINO_BAUDRATE = 115200               # 串口通信波特率（默认：115200）
ARDUINO_TIMEOUT = 1                     # 串口读取超时时间（秒），默认：1.0
ARDUINO_WRITE_TIMEOUT = 1               # 串口写入超时时间（秒），默认：1.0

# 线程安全配置
ARDUINO_LOCK_TIMEOUT = 1.0     # 最大等待锁的时间（秒），默认：1.0
ARDUINO_MAX_RETRIES = 3        # 最大重试次数（默认：3）

# 摄像头配置
CAMERA_TYPE = "WEBCAM"   # 摄像头类型，需简要说明（如："WEBCAM"、"PICAM"等）
CAMERA_INDEX = 0         # 摄像头索引（默认：0）

# 智驾相关配置
DRIVE_LOOP_HZ = 60      # 系统运行的循环频率（Hz）
AI_THROTTLE_MULT = 1.1  # 自动驾驶时，油门的缩放因子（默认：1.1）

#--------------------------For DonkeySim 驴车模拟器相关配置
# DonkeySim 驴车模拟器相关配置
DONKEY_GYM = False           # 是否使用DonkeySim模拟器（默认：False）
DONKEY_SIM_PATH = "remote"  # DonkeySim模拟器的安装路基（默认："remote"，需要先运行DonkeySim模拟器）
GYM_CONF = { 
    "body_style" : "donkey",        # 车子模型（"donkey" | "bare" | "car01" | "f1" | "cybertruck")
    "body_rgb" : (128, 128, 128),   # 车子颜色(红, 绿, 蓝)，数值范围（0-255）
    "car_name" : "DKC",             # 小车名称
    "font_size" : 50                # 车名字体大小
    } 


def get_wsl_host_ip():
    # 尝试 1: 使用 ip route 获取默认网关 (WSL2 中 Windows 主机 IP 就是默认网关)
    try:
        result = subprocess.run(['ip', 'route', 'show'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode == 0:
            match = re.search(r'default via (\d+\.\d+\.\d+\.\d+)', result.stdout)
            if match:
                return match.group(1)
    except Exception:
        pass

    # 尝试 2: 使用 ipconfig.exe (能获取 Windows 局域网 IP)
    try:
        result = subprocess.run(['ipconfig.exe'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode == 0:
            output = result.stdout
            try:
                text = output.decode('gbk')
            except:
                text = output.decode('utf-8', errors='ignore')
            
            ips = []
            for line in text.splitlines():
                if "IPv4" in line or "IP Address" in line:
                    match = re.search(r'(\d+\.\d+\.\d+\.\d+)', line)
                    if match:
                        ips.append(match.group(1))
            
            for ip in ips:
                if ip.startswith("192.168."):
                    return ip
            
            for ip in ips:
                if not ip.startswith("127.") and not ip.startswith("172.") and not ip.startswith("10.255."):
                    return ip
    except Exception:
        pass
    
    return "127.0.0.1"

SIM_HOST = get_wsl_host_ip()
#SIM_HOST = "127.0.0.1"  # 模拟器主机IP地址（默认：127.0.0.1-代表本机，若不在同一系统，则需指定模拟器主机IP地址）
WEB_CONTROL_PORT = 8887  # 控制网页的端口号（默认：8887）
USE_JOYSTICK_AS_DEFAULT = False  # 是否将摇杆作为默认输入设备（默认：否）


def _should_limit_gpu_memory():
    args = sys.argv if hasattr(sys, "argv") else []
    if not args:
        return False
    argv0 = os.path.basename(args[0])
    if argv0 == "donkey" and "train" in args:
        return True
    if argv0 in {"train.py", "manage.py"} and "train" in args:
        return True
    return False

if _should_limit_gpu_memory():
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
    try:
        import tensorflow as tf
        gpus = tf.config.list_physical_devices("GPU")
        if gpus:
            for gpu in gpus:
                tf.config.set_logical_device_configuration(
                    gpu,
                    [tf.config.LogicalDeviceConfiguration(memory_limit=7168)],
                )
    except Exception:
        pass

MAX_EPOCHS = 60   # 最大训练轮数（默认：60）

#--------------------------End 结尾

