"""donkey web 与 donkey drive 的公共参数必须保持一致。

两个命令的参数表此前是逐行复制的，改动要同步两处、漏一处即行为分叉；
现在共用 WEB_COMMON_ARGS，这里钉住合并后的默认值契约。
"""
from donkeycar.management.base import Drive, Web


def test_web_and_drive_share_common_defaults():
    web = Web().parse_args([])
    drive = Drive().parse_args([])

    assert web.route == '/'
    assert drive.route == '/drive'

    for attr in ('path', 'frontend_port', 'backend_port', 'backend_host',
                 'install_deps', 'open', 'dev', 'debug'):
        assert getattr(web, attr) == getattr(drive, attr), attr

    assert web.backend_host == '127.0.0.1'
    assert drive.backend_host == '127.0.0.1'


def test_drive_has_car_only_args():
    drive = Drive().parse_args([])
    assert drive.car is None
    assert drive.model is None
    assert drive.type is None
    assert drive.js is False
