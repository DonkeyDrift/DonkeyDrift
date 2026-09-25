import numpy as np

from donkeycar.parts.simulation import SquareBoxCamera


def test_square_box_camera_returns_uint8():
    """合成相机帧必须与真实相机一致为 uint8——WebRTC 视频轨道的
    av.VideoFrame.from_ndarray 拒绝 float 数组（曾致 square 模板视频流
    线程 ValueError）。"""
    cam = SquareBoxCamera(resolution=(120, 160))
    frame = cam.run(x=80, y=60)
    assert frame.dtype == np.uint8
    assert frame.shape == (120, 160, 3)
