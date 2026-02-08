# 驾驶参数持久化系统文档

## 概述

实现了一个完整的参数持久化系统，支持 PID 控制参数、回中参数和加速度调节参数的安全存储和加载。

## 功能特性

### 1. 多层存储机制
- **浏览器 localStorage**: 客户端即时保存，快速访问
- **服务器文件存储**: 持久化到 `~/mycar/drive_params.json`
- **双重保护**: 两种存储互为备份

### 2. 数据验证
- 参数类型检查
- 数值范围验证
- 版本控制支持

### 3. 用户界面
- **实时保存**: 滑块调整时自动保存
- **参数管理面板**: 提供4个功能按钮
  - 重置默认值
  - 导出参数（JSON文件）
  - 导入参数
  - 从服务器加载

### 4. 错误处理
- 智能通知系统（右上角弹窗）
- 详细日志记录
- 降级策略（服务器失败时使用本地）

## 技术实现

### 前端 (main.js)

#### 核心函数

**参数验证**
```javascript
validateParams(params)
// 验证参数格式和数值范围
// 返回: boolean
```

**加载参数**
```javascript
loadPersistedParams()
// 从 localStorage 加载参数
// 自动验证和版本检查
// 返回: boolean (是否成功)
```

**保存参数**
```javascript
savePersistedParams()
// 保存到 localStorage
// 同时触发服务器保存
// 返回: boolean (是否成功)
```

**服务器交互**
```javascript
saveParamsToServer()
// 通过 WebSocket 发送参数到服务器
// 消息格式: { msg_type: 'save_params', params: {...} }

loadParamsFromServer()
// HTTP GET /api/get_params
// 从服务器加载参数
```

**参数管理**
```javascript
resetParams()        // 重置到默认值
exportParams()       // 导出为 JSON 文件
importParams(file)   // 从文件导入
```

**通知系统**
```javascript
showNotification(message, type, duration)
// type: 'success' | 'error' | 'warning' | 'info'
// duration: 显示时长（毫秒）
```

#### 默认参数配置
```javascript
const DEFAULT_PARAMS = {
    'pid': {
        'kp': 0.8,    // 比例系数 (0-3)
        'ki': 0.0,    // 积分系数 (0-1)
        'kd': 0.05,   // 微分系数 (0-0.1)
    },
    'recenterRate': 0.35,  // 回中速度 (0-2)
    'steerRate': 1.2,      // 转向角速度 (0-3)
    'accelRate': 1.0,      // 加速率 (0-3)
    'brakeRate': 1.2       // 刹车率 (0-3)
};
```

#### 数据格式（localStorage）
```json
{
    "version": "2.0",
    "timestamp": "2026-02-09T10:30:45.123Z",
    "params": {
        "pid": { "kp": 0.8, "ki": 0.0, "kd": 0.05 },
        "recenterRate": 0.35,
        "steerRate": 1.2,
        "accelRate": 1.0,
        "brakeRate": 1.2
    }
}
```

### 后端 (web.py)

#### ParamsManager 类

**初始化**
```python
ParamsManager(config_dir=None)
# config_dir: 配置文件目录，默认 ~/mycar/
# 自动创建目录和文件
```

**方法**
```python
validate_params(params) -> bool
# 验证参数格式和范围

load() -> dict
# 从文件加载参数
# 返回验证后的参数字典

save(params) -> bool
# 保存参数到文件
# 使用原子性写入（临时文件+重命名）
```

#### HTTP API

**获取参数**
```
GET /api/get_params

响应:
{
    "success": true,
    "params": { ... },
    "timestamp": "2026-02-09 10:30:45"
}
```

**保存参数**
```
POST /api/save_params

请求体:
{
    "params": { ... }
}

响应:
{
    "success": true,
    "message": "Parameters saved successfully",
    "timestamp": "2026-02-09 10:30:45"
}
```

#### WebSocket 消息

**保存参数**
```json
{
    "msg_type": "save_params",
    "params": { ... },
    "timestamp": "2026-02-09T10:30:45.123Z"
}
```

## 文件结构

```
~/mycar/
├── drive_params.json       # 主配置文件
└── drive_params.json.tmp   # 临时文件（写入时使用）

浏览器:
localStorage['dkc_drive_params'] = { version, timestamp, params }
```

## 使用流程

### 初始化流程
1. 服务器启动 → 创建 ParamsManager
2. 客户端连接 → 加载 localStorage
3. 如果本地无参数 → 从服务器加载
4. 如果服务器无参数 → 使用默认值

### 调整参数流程
1. 用户拖动滑块
2. 触发 `input` 事件
3. 更新 `state.params`
4. 调用 `savePersistedParams()`
5. 保存到 localStorage（同步）
6. 发送到服务器（异步，通过 WebSocket）
7. 服务器写入文件

### 导入/导出流程
**导出:**
1. 点击"导出参数"按钮
2. 创建 JSON Blob
3. 触发浏览器下载

**导入:**
1. 点击"导入参数"
2. 选择 JSON 文件
3. 读取并验证
4. 更新 UI 和 state
5. 保存到本地和服务器

## 异常处理

### 客户端
- localStorage 失败 → 显示错误通知，继续运行
- 服务器保存失败 → 仅警告日志，本地已保存
- 参数验证失败 → 使用默认值，显示警告

### 服务器端
- 文件读取失败 → 返回默认值
- 文件写入失败 → 返回错误，原文件不变
- 参数验证失败 → 拒绝保存

## 参数范围约束

| 参数 | 最小值 | 最大值 | 步进 | 说明 |
|------|--------|--------|------|------|
| Kp | 0 | 3 | 0.05 | PID 比例系数 |
| Ki | 0 | 1 | 0.01 | PID 积分系数 |
| Kd | 0 | 0.1 | 0.01 | PID 微分系数 |
| 回中速度 | 0 | 2 | 0.05 | 角度/秒 |
| 转向角速度 | 0 | 3 | 0.05 | 角度/秒 |
| 加速率 | 0 | 3 | 0.05 | 单位/秒 |
| 刹车率 | 0 | 3 | 0.05 | 单位/秒 |

## 安全特性

1. **原子性写入**: 使用临时文件 + rename，防止崩溃导致数据损坏
2. **参数验证**: 双重验证（前端+后端），防止非法数据
3. **版本控制**: 支持未来数据迁移
4. **降级策略**: 多层存储保证数据不丢失
5. **用户确认**: 重置操作需要确认对话框

## 调试建议

### 查看保存的参数
**浏览器控制台:**
```javascript
// 查看 localStorage
JSON.parse(localStorage.getItem('dkc_drive_params'))

// 查看当前状态
driveHandler.state.params
```

**服务器:**
```bash
cat ~/mycar/drive_params.json
```

### 日志位置
- 浏览器: F12 → Console 标签
- 服务器: stdout（运行终端）

### 常见问题

**Q: 参数没有保存？**
- 检查 localStorage 是否禁用
- 检查控制台错误日志
- 验证参数是否在合法范围内

**Q: 刷新后参数丢失？**
- 检查浏览器缓存是否清除
- 强制刷新: Ctrl+Shift+R

**Q: 服务器参数不同步？**
- 检查 WebSocket 连接状态
- 手动点击"从服务器加载"按钮

## 版本历史

**v2.0 (2026-02-09)**
- 实现完整的持久化系统
- 添加参数管理面板
- 支持导入/导出
- 增强错误处理
- 添加通知系统

**v1.0 (初始版本)**
- 基本的 localStorage 保存
- 简单的参数加载
