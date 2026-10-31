# Debug Session: joystick-control
- Status: [OPEN]
- progress_status: collecting
- Issue: 页面摇杆无法控制模拟器车辆。
- Project root: C:\Dev\DDC\DonkeyDrift
- Evidence directory: C:\Users\cross\AppData\Local\Temp\DonkeyDrift-joystick-control
- Environment file: C:\Users\cross\AppData\Local\Temp\DonkeyDrift-joystick-control\joystick-control.env
- Log file: C:\Users\cross\AppData\Local\Temp\DonkeyDrift-joystick-control\trae-debug-log-joystick-control.ndjson
- Evidence source: Debug Server http://127.0.0.1:7777/event

## Reproduction
启动 Drive，操作虚拟摇杆，观察车辆和遥测。

## Hypotheses
| ID | 假设 | 优先级 | 可证伪信号 | 结论 |
|----|------|--------|------------|------|
| A | 车端未运行或未连接 | 高 | 车端进程和服务连接状态 | INCONCLUSIVE |
| B | 页面与车端连接不同后端 | 高 | 端口及各服务连接状态 | INCONCLUSIVE |
| C | 页面未发送非零输入 | 中 | 摇杆事件与发送消息 | INCONCLUSIVE |
| D | 车端收到输入但未传到模拟器 | 中 | 控制消息与车辆遥测 | INCONCLUSIVE |

## Observations
初次检查仅有模拟器监听 9091/9092；网页后端和车端没有运行。尚不能确定用户操作时的状态。
Debug Server 健康检查与事件探针成功；等待通过 TUI 启动 Drive 以复现。

## Final Evidence Gate
- progress_status: collecting
- Evidence sources: process list and listening ports; runtime reproduction pending.
