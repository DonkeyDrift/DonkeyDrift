# 参数持久化功能测试指南

## 快速测试步骤

### 1. 重启服务器
```bash
cd ~/mycar
python manage.py drive
```

**预期输出:**
```
Parameters manager initialized. Config file: /home/dkc/mycar/drive_params.json
```

### 2. 在浏览器中访问控制页面

**Edge 浏览器测试:**
1. 访问 `http://localhost:8887/drive`
2. 按 **Ctrl + Shift + R** 强制刷新（清除缓存）
3. 打开开发者工具 (F12)

### 3. 测试本地存储加载

**浏览器控制台执行:**
```javascript
// 查看当前参数
console.log(driveHandler.state.params);

// 查看 localStorage
console.log(JSON.parse(localStorage.getItem('dkc_drive_params')));
```

### 4. 测试参数调整和保存

1. 滚动页面找到 **"PID / 回中 / 加速度调节"** 面板
2. 调整任意滑块（例如 Kp 从 0.8 改为 1.0）
3. **观察右上角通知**（应该没有通知，因为自动保存是静默的）

**验证保存成功:**
```javascript
// 控制台应该显示
// "Parameters saved successfully"
```

**检查 localStorage:**
```javascript
let saved = JSON.parse(localStorage.getItem('dkc_drive_params'));
console.log('Saved Kp:', saved.params.pid.kp); // 应该是 1.0
```

**检查服务器文件:**
```bash
cat ~/mycar/drive_params.json
```

### 5. 测试参数持久化（刷新后保留）

1. 刷新页面 (F5)
2. 检查滑块值是否保持修改后的值

**控制台验证:**
```javascript
console.log('After refresh, Kp:', driveHandler.state.params.pid.kp);
// 应该仍然是 1.0
```

### 6. 测试重置功能

1. 找到 **"参数管理"** 面板
2. 点击 **"重置默认值"** 按钮
3. 确认对话框点击"确定"
4. **观察右上角绿色通知**: "参数已重置为默认值"

**验证:**
```javascript
console.log('After reset, Kp:', driveHandler.state.params.pid.kp);
// 应该回到 0.8
```

### 7. 测试导出功能

1. 点击 **"导出参数"** 按钮
2. **观察右上角绿色通知**: "参数导出成功"
3. 浏览器应该自动下载文件: `donkeycar-params-2026-02-09.json`

**查看导出文件:**
```json
{
  "version": "2.0",
  "exportDate": "2026-02-09T...",
  "params": {
    "pid": { "kp": 0.8, "ki": 0.0, "kd": 0.05 },
    ...
  }
}
```

### 8. 测试导入功能

1. 手动编辑导出的 JSON 文件，修改某个值（如 Kp 改为 2.5）
2. 点击 **"导入参数"** 按钮
3. 选择刚才编辑的文件
4. **观察右上角绿色通知**: "参数导入成功"
5. 检查滑块是否更新为新值

### 9. 测试从服务器加载

1. 手动编辑服务器文件:
```bash
nano ~/mycar/drive_params.json
# 修改某个参数值
```

2. 在浏览器中点击 **"从服务器加载"** 按钮
3. **观察右上角绿色通知**: "从服务器加载参数成功"
4. 检查 UI 是否更新

### 10. 测试 WebSocket 自动保存

**监听 WebSocket 消息:**
```javascript
// 在调整滑块前，打开网络面板
// Network → WS → wsDrive → Messages
// 调整滑块后应该看到 save_params 消息
```

**服务器日志应该显示:**
```
Parameters saved via WebSocket: True
Parameters saved to /home/dkc/mycar/drive_params.json
```

### 11. 测试 Kd 参数范围

1. 找到 Kd 滑块
2. 验证范围: 0 到 0.1
3. 验证步进: 0.01
4. 拖动滑块，应该只能选择 0.00, 0.01, 0.02, ... 0.10

## 错误场景测试

### 测试 1: localStorage 禁用
```javascript
// 模拟 localStorage 失败
localStorage.setItem = function() { throw new Error('Quota exceeded'); };

// 调整滑块，应该看到错误通知
// "参数保存失败: Quota exceeded"
```

### 测试 2: 服务器连接断开
```bash
# 停止服务器
# 在浏览器中调整参数
# 应该看到警告日志: "WebSocket not connected, skipping server save"
# 但本地存储应该仍然成功
```

### 测试 3: 无效参数导入
创建错误的 JSON 文件:
```json
{
  "version": "2.0",
  "params": {
    "pid": { "kp": 999 }  // 超出范围
  }
}
```

导入应该失败，显示错误通知: "导入的文件格式无效或参数不合法"

### 测试 4: HTTP API 直接测试

**使用 curl 测试:**
```bash
# 获取参数
curl http://localhost:8887/api/get_params

# 保存参数
curl -X POST http://localhost:8887/api/save_params \
  -H "Content-Type: application/json" \
  -d '{
    "params": {
      "pid": {"kp": 1.5, "ki": 0.0, "kd": 0.05},
      "recenterRate": 0.5,
      "steerRate": 1.5,
      "accelRate": 1.2,
      "brakeRate": 1.3
    }
  }'
```

## 通知系统测试

### 验证通知显示
- **成功 (绿色)**: 参数加载、保存、导出、导入成功
- **错误 (红色)**: 文件读取失败、验证失败
- **警告 (黄色)**: 参数验证失败但继续使用默认值
- **信息 (蓝色)**: 未使用（可自行扩展）

### 验证通知动画
- 从右侧滑入
- 停留 2-3 秒
- 向右侧滑出并消失

### 验证多个通知
快速连续触发多个操作，应该看到通知堆叠显示

## 性能测试

### 快速调整滑块
1. 快速连续拖动滑块
2. 每次调整都应该触发保存
3. 不应该出现界面卡顿
4. 控制台日志不应该有错误

### 大量导入导出
1. 导出参数 10 次
2. 应该不出现内存泄漏
3. 文件名应该包含日期（避免覆盖）

## 浏览器兼容性测试

测试以下浏览器:
- ✅ Chrome/Edge (已确认 IKJL 控制和持久化)
- ✅ Firefox
- ✅ Safari (Mac)
- ✅ CodeBuddy 内置浏览器

## 成功标准

✅ 所有测试通过的标志:
1. 参数调整后刷新页面仍然保留
2. 服务器重启后参数从文件加载
3. 导入/导出功能正常
4. 错误场景有明确提示
5. 无 JavaScript 错误
6. UI 响应流畅

## 故障排查

### 问题: 参数不保存
**检查清单:**
- [ ] 浏览器是否禁用 localStorage
- [ ] 控制台是否有错误
- [ ] WebSocket 是否连接
- [ ] 服务器日志是否有错误

### 问题: 刷新后参数丢失
**解决方案:**
1. 强制刷新 (Ctrl+Shift+R)
2. 清除浏览器缓存
3. 检查 URL 是否正确（不要用 IP 和 localhost 混用）

### 问题: UI 不更新
**解决方案:**
1. 检查 `applyParamsToUI()` 是否被调用
2. 检查 HTML 元素 ID 是否正确
3. 查看浏览器控制台是否有绑定错误

### 问题: 服务器文件损坏
**恢复方法:**
```bash
# 删除损坏的文件，将使用默认值
rm ~/mycar/drive_params.json

# 或者手动创建
cat > ~/mycar/drive_params.json << EOF
{
  "version": "2.0",
  "timestamp": "2026-02-09 00:00:00",
  "params": {
    "pid": {"kp": 0.8, "ki": 0.0, "kd": 0.05},
    "recenterRate": 0.35,
    "steerRate": 1.2,
    "accelRate": 1.0,
    "brakeRate": 1.2
  }
}
EOF
```

## 日志检查点

### 正常启动日志
```
Parameters manager initialized. Config file: /home/dkc/mycar/drive_params.json
Parameters loaded from /home/dkc/mycar/drive_params.json
```

### 首次运行日志
```
Parameters manager initialized. Config file: /home/dkc/mycar/drive_params.json
No saved parameters found, using defaults
```

### 参数保存日志
```
Parameters saved via WebSocket: True
Parameters saved to /home/dkc/mycar/drive_params.json
```

### 参数验证失败日志
```
Loaded parameters validation failed, using defaults
ERROR: Failed to save parameters: Parameters validation failed
```
