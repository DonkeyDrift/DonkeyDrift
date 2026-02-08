# 方向键控制系统修复方案

## 问题诊断

### 原始问题
- **现象**: 方向键只能控制页面滚动，无法驱动小车
- **根本原因**: 
  1. 事件监听器优先级不足，浏览器默认行为先执行
  2. 重复绑定导致事件处理混乱
  3. `preventDefault()` 调用时机过晚

## 修复方案

### 1. 事件捕获优先级提升

**核心改进**: 使用原生 `addEventListener` 的**捕获阶段**（第三参数 `true`）拦截方向键

```javascript
// 在事件传播的捕获阶段就拦截方向键，优先级最高
window.addEventListener('keydown', function(e) {
    const arrowKeys = [37, 38, 39, 40]; // left, up, right, down
    if(arrowKeys.includes(e.keyCode || e.which)) {
      e.preventDefault();        // 阻止默认滚动
      e.stopPropagation();       // 停止事件传播
      console.log('Arrow key down:', e.keyCode || e.which);
      
      switch(e.keyCode || e.which) {
        case 37: state.keyInput.left = true; break;   // 左
        case 38: state.keyInput.up = true; break;     // 上
        case 39: state.keyInput.right = true; break;  // 右
        case 40: state.keyInput.down = true; break;   // 下
      }
      return false;
    }
}, true); // ⚠️ 关键：使用捕获阶段
```

**事件传播三阶段**:
```
1. 捕获阶段 (Capture) ← 我们在这里拦截
2. 目标阶段 (Target)
3. 冒泡阶段 (Bubble)   ← 浏览器默认行为在这里
```

### 2. 去除重复监听器

**问题代码**（已删除）:
```javascript
// ❌ 旧代码：jQuery 和原生 API 重复绑定
$(document).keydown(keydownHandler);
$(document).keyup(keyupHandler);
window.addEventListener('keydown', keydownHandler, {passive: false});
window.addEventListener('keyup', keyupHandler, {passive: false});
```

**修复后**:
```javascript
// ✅ 方向键用原生捕获（优先级高）
window.addEventListener('keydown', handler, true);

// ✅ 其他功能键用 jQuery（代码简洁）
$(document).keydown(function(e) {
    if(e.which == 32) { e.preventDefault(); toggleBrake() }  // 空格
    if(e.which == 82) { toggleRecording() }  // R
    // ...
});
```

### 3. 增量控制循环逻辑

方向键控制采用**持续积分 + 自动回中**模式：

```javascript
var arrowControlLoop = function() {
  setTimeout(function() {
    const dt = (now - lastTs) / 1000.0; // 时间增量
    
    // 左右控制：按住时角度持续增加
    if(state.keyInput.left && !state.keyInput.right) {
      state.tele.user.angle -= state.params.steerRate * dt;
    } else if(!state.keyInput.left && !state.keyInput.right) {
      // 松开时自动回中
      state.tele.user.angle -= sign * recenterRate * dt;
    }
    
    // PID 平滑处理（模拟竞速游戏手感）
    pidState.output += kp*error + ki*integral + kd*derivative;
    state.tele.user.angle = pidState.output;
    
    // 前后控制：松开自动减速
    if(state.keyInput.up) {
      state.tele.user.throttle += accelRate * dt;
    } else {
      state.tele.user.throttle -= decelRate * dt; // 自动减速
    }
    
    postDrive(['angle','throttle']); // 发送 WebSocket
    arrowControlLoop(); // 50ms 循环
  }, 50);
}
```

### 4. PID 控制器参数

模拟"极品飞车"竞速手感：

| 参数 | 默认值 | 作用 |
|------|--------|------|
| **Kp** | 0.8 | 比例增益：响应速度 |
| **Ki** | 0.0 | 积分增益：消除稳态误差 |
| **Kd** | 0.15 | 微分增益：抑制超调，增加阻尼 |
| **回中速度** | 0.35 角/秒 | 松开方向键后回中速度 |
| **转向角速度** | 1.2 角/秒 | 按住方向键时转向速度 |
| **加速率** | 1.0 /秒 | 油门变化速率 |
| **刹车率** | 1.2 /秒 | 松开油门的减速率 |

## 调试与验证

### 浏览器控制台输出

正常工作时会看到：
```
Arrow key down: 38          // 按下上方向键
Arrow keys active: {up: true, down: false, left: false, right: false}
Sending control: {angle: 0.000, throttle: 0.152}
Posting {"angle":0.152,"throttle":0.152}
Arrow key up: 38            // 松开上方向键
Arrow control deactivated   // 自动回零完成
```

### 验证步骤

1. **刷新驾驶页面** `/drive`
2. **打开浏览器开发者工具** (F12) → Console
3. **按住上方向键** → 应看到 "Arrow key down: 38" 和油门数值递增
4. **松开方向键** → 应看到油门自动减速至 0
5. **按住左/右方向键** → 角度持续变化，松开后自动回中
6. **调整滑块** → 实时改变 PID、回中速度等参数并持久化

### 排查清单

若方向键仍无响应，检查：

- [ ] WebSocket 是否连接成功（控制台无 "WS not open" 警告）
- [ ] 是否按下 "Start Vehicle" 按钮（`state.brakeOn` 应为 false）
- [ ] 控制台是否显示 "Arrow key down" 日志
- [ ] 是否有 JavaScript 错误阻断执行
- [ ] 参数滑块值是否正常（回中/转向速度不应为 0）

## 架构优势

### 对比原 IKJL 键控制

| 特性 | IKJL 键 | 方向键（新） |
|------|---------|-------------|
| 控制方式 | 离散步进（每次 ±0.05） | 连续积分（时间比例） |
| 松开行为 | 保持当前值 | **自动回中/减速** |
| 手感 | 阶梯式 | **PID 平滑** |
| 适用场景 | 精确调试 | **竞速驾驶** |

### 可调参数持久化

通过 `localStorage` 存储，用户调整后刷新页面参数保留：

```javascript
// 保存
localStorage.setItem('dkc_drive_params', JSON.stringify({
  params: {
    pid: {kp: 0.8, ki: 0.0, kd: 0.15},
    recenterRate: 0.35,
    // ...
  }
}));

// 加载
const data = JSON.parse(localStorage.getItem('dkc_drive_params'));
updateState(state.params, data.params);
```

## 后续优化方向

1. **手感预设**: 提供"街道"/"赛道"/"越野"等预设参数组合
2. **按键映射**: 允许用户自定义控制按键
3. **力反馈模拟**: 根据速度调整转向响应曲线
4. **录制回放**: 记录按键序列用于自动驾驶训练
5. **碰撞保护**: 检测异常加速度自动刹车

## 代码位置

- **JS 逻辑**: `donkeycar/parts/web_controller/templates/static/main.js`
  - 第 252-311 行：事件监听器绑定
  - 第 93-181 行：方向键控制循环
  - 第 31-42 行：可调参数定义
  
- **UI 界面**: `donkeycar/parts/web_controller/templates/vehicle.html`
  - 第 109-176 行：PID/回中/加速度调节滑块面板

- **后端接口**: `donkeycar/parts/web_controller/web.py`
  - 第 285-308 行：WebSocketDriveAPI 处理控制指令
