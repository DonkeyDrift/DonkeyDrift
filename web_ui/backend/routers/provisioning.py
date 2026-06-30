"""配网 API 路由。

提供 WiFi 配网状态查询、手动触发连接、WiFi 扫描和串口扫描功能。
当 Vehicle 未运行时，通过后端独立维护配网状态。
"""

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()


# ------------------------------------------------------------------
# 请求模型
# ------------------------------------------------------------------
class ConnectRequest(BaseModel):
    ssid: str
    password: str = ""


# ------------------------------------------------------------------
# 模块级状态（参考 tub.py 的 current_tub 模式）
# ------------------------------------------------------------------
_provisioning_state = {
    "status": "idle",
    "ssid": "",
    "ip": "",
    "error": "",
}


def _update_state(status=None, ssid=None, ip=None, error=None):
    """线程安全更新配网状态（仅供内部和 ProvisioningPart 使用）。"""
    if status is not None:
        _provisioning_state["status"] = status
    if ssid is not None:
        _provisioning_state["ssid"] = ssid
    if ip is not None:
        _provisioning_state["ip"] = ip
    if error is not None:
        _provisioning_state["error"] = error


# ------------------------------------------------------------------
# 路由
# ------------------------------------------------------------------
@router.get("/status")
async def get_provisioning_status():
    """获取当前配网状态。

    Returns:
        {
            "status": "idle" | "connecting" | "connected" | "failed",
            "ssid": "当前 SSID",
            "ip": "分配到的 IP 地址",
            "error": "失败原因（如果失败）"
        }
    """
    return dict(_provisioning_state)


@router.post("/connect")
async def trigger_connect(request: ConnectRequest):
    """手动触发 WiFi 配网连接。

    将配网请求写入全局状态，等待后台 ProvisioningPart 或守护进程处理。
    如果 WifiManager 可用则同步执行连接。

    Args:
        request: {"ssid": "目标 WiFi 名称", "password": "WiFi 密码"}

    Returns:
        {"status": True, "message": "..."}
    """
    from donkeycar.parts.provisioning import WifiManager
    import threading

    ssid = request.ssid.strip()
    if not ssid:
        raise HTTPException(status_code=400, detail="SSID 不能为空")

    # 更新状态
    _update_state(status="connecting", ssid=ssid, ip="", error="")

    # 在后台线程中执行配网，避免阻塞 API 响应
    def _do_connect():
        try:
            wm = WifiManager()
            wm.disconnect_ap()
            import time
            time.sleep(1)
            success, result = wm.connect(ssid, request.password)
            if success:
                _update_state(status="connected", ip=result, error="")
                logger.info("配网成功: SSID=%s, IP=%s", ssid, result)
            else:
                _update_state(status="failed", error=result)
                logger.error("配网失败: SSID=%s, 原因=%s", ssid, result)
        except Exception as exc:
            _update_state(status="failed", error=str(exc))
            logger.exception("配网异常: SSID=%s", ssid)

    thread = threading.Thread(target=_do_connect, daemon=True)
    thread.start()

    return {"status": True, "message": f"开始连接 {ssid}，请轮询 /status 获取结果"}


@router.post("/scan")
async def scan_wifi():
    """扫描附近 WiFi 网络。

    Returns:
        {"networks": [{"ssid": "...", "signal": 90, "security": "WPA2"}, ...]}
    """
    from donkeycar.parts.provisioning import WifiManager

    try:
        wm = WifiManager()
        networks = wm.scan_networks()
        return {"networks": networks}
    except Exception as exc:
        logger.exception("WiFi 扫描失败")
        raise HTTPException(status_code=500, detail=f"WiFi 扫描失败: {exc}")


@router.get("/serial/scan")
async def scan_serial_ports():
    """扫描可用串口设备，查找配网 ESP32。

    Returns:
        {"ports": ["/dev/ttyS5", "/dev/ttyUSB0", ...]}  或
        {"found": True, "port": "/dev/ttyS5", "rtt_ms": 12.5}
    """
    from donkeycar.parts.provisioning import ProvisioningPart

    try:
        port, rtt_ms = ProvisioningPart.scan_serial_ports()
        if port:
            return {"found": True, "port": port, "rtt_ms": round(rtt_ms, 2)}
        else:
            return {"found": False, "port": None, "rtt_ms": None}
    except Exception as exc:
        logger.exception("串口扫描失败")
        raise HTTPException(status_code=500, detail=f"串口扫描失败: {exc}")
