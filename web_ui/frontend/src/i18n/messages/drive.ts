// drive namespace: zh values mirror the current UI strings verbatim (the
// "Chinese interface" is exactly today's mixed zh/en UI); en values are the
// full English translation of every entry.
export const drive: { zh: Record<string, string>; en: Record<string, string> } = {
  zh: {
    // DrivePage
    'drive.title': '驾驶控制台',
    'drive.record': '录制',
    'drive.recording': '录制中 {duration}',
    'drive.recordedCount': '已录制条数 {count}',
    'drive.parkLocked': 'Park 锁定 · 油门被钳 0',
    'drive.virtualJoystick': '虚拟摇杆',
    'drive.collapseJoystick': '折叠虚拟摇杆',
    'drive.expandJoystick': '展开虚拟摇杆',
    'drive.mouseTouchSupport': '支持鼠标 / 触屏',
    'drive.hotkeysLine1': '键盘快捷键: I 前进 · K 倒车 · J 左转 · L 右转',
    'drive.hotkeysLine2': 'R 切换录制 · M 切换模式',
    // DriveModeSelector
    'drive.modeUser': '手动',
    'drive.modeSemiAuto': '半自动',
    'drive.modeFullAuto': '全自动',
    // InputSourceSelector
    'drive.inputSource': '输入源',
    'drive.sourceJoystick': '摇杆',
    'drive.sourceKeyboard': '键盘',
    'drive.sourceGamepad': '手柄',
    'drive.sourceGyro': '陀螺仪',
    'drive.gamepadConnected': '已连接手柄',
    'drive.gamepadNotDetected': '未检测到手柄',
    'drive.gyroSupported': '设备支持陀螺仪',
    'drive.gyroNotSupported': '设备不支持陀螺仪',
    // ModelSelector
    'drive.noModel': '无模型',
    'drive.currentModel': '当前模型',
    // ProgrammableButtons
    'drive.hintW1': '增加油门上限',
    'drive.hintW2': '降低油门上限',
    'drive.hintW3': '切换模型',
    'drive.hintW4': '重置方向',
    'drive.hintW5': '紧急停止',
    // ControlBars
    'drive.turnLeft': '左 转',
    'drive.steering': '转 向',
    'drive.turnRight': '右 转',
  },
  en: {
    // DrivePage
    'drive.title': 'Drive Console',
    'drive.record': 'Record',
    'drive.recording': 'Recording {duration}',
    'drive.recordedCount': 'Recorded: {count}',
    'drive.parkLocked': 'Park locked · throttle clamped to 0',
    'drive.virtualJoystick': 'Virtual Joystick',
    'drive.collapseJoystick': 'Collapse virtual joystick',
    'drive.expandJoystick': 'Expand virtual joystick',
    'drive.mouseTouchSupport': 'Mouse / touch supported',
    'drive.hotkeysLine1': 'Keyboard shortcuts: I forward · K reverse · J left · L right',
    'drive.hotkeysLine2': 'R toggle recording · M cycle mode',
    // DriveModeSelector
    'drive.modeUser': 'Manual',
    'drive.modeSemiAuto': 'Semi-Auto',
    'drive.modeFullAuto': 'Full Auto',
    // InputSourceSelector
    'drive.inputSource': 'Input Source',
    'drive.sourceJoystick': 'Joystick',
    'drive.sourceKeyboard': 'Keyboard',
    'drive.sourceGamepad': 'Gamepad',
    'drive.sourceGyro': 'Gyroscope',
    'drive.gamepadConnected': 'Gamepad connected',
    'drive.gamepadNotDetected': 'No gamepad detected',
    'drive.gyroSupported': 'Device supports gyroscope',
    'drive.gyroNotSupported': 'Device does not support gyroscope',
    // ModelSelector
    'drive.noModel': 'No model',
    'drive.currentModel': 'Current model',
    // ProgrammableButtons
    'drive.hintW1': 'Increase throttle limit',
    'drive.hintW2': 'Decrease throttle limit',
    'drive.hintW3': 'Switch model',
    'drive.hintW4': 'Reset steering',
    'drive.hintW5': 'Emergency stop',
    // ControlBars
    'drive.turnLeft': 'Left',
    'drive.steering': 'Steering',
    'drive.turnRight': 'Right',
  },
};
