# Debug Session: model-preview-err-aborted

## Session Info
- **Session ID**: model-preview-err-aborted
- **Created**: 2026-05-22
- **Status**: [OPEN]

## Symptoms
- **Error**: `net::ERR_ABORTED http://172.24.53.251:5188/api/trainer/models/preview?path=%2Fhome%2Fdkc%2Fprojects%2Fmycar%2Fmodels%2Fpilot_1778591936253.png`
- **Endpoint**: `/api/trainer/models/preview`
- **File**: `/home/dkc/projects/mycar/models/pilot_1778591936253.png` (PNG 图片)

## Environment
- Frontend: Vite dev server on port 5188
- Backend: FastAPI on port 8000
- OS: Linux

## Hypotheses

### H1: 后端服务器未运行或崩溃
- **假设**: FastAPI 后端服务器 (uvicorn) 未运行或已崩溃
- **验证方法**: 检查 8000 端口是否有服务监听

### H2: 预览端点不存在或路由错误
- **假设**: `/api/trainer/models/preview` 路由未在 FastAPI 中定义
- **验证方法**: 检查 `web_ui/backend/` 中的路由配置

### H3: 文件不存在或路径问题
- **假设**: 请求的 PNG 文件在服务器上不存在
- **验证方法**: 检查文件是否存在

### H4: 预览处理函数抛出异常
- **假设**: 预览端点的处理函数在读取/处理图片时发生异常
- **验证方法**: 添加日志/检查后端控制台输出

### H5: 请求超时
- **假设**: 图片文件过大或处理时间过长导致请求超时
- **验证方法**: 检查请求处理时间和文件大小

## Investigation Progress

### Step 1: 检查后端服务状态
- [ ] 检查 8000 端口是否监听
- [ ] 检查后端进程是否运行

### Step 2: 检查路由定义
- [ ] 查看 trainer.py 路由文件

### Step 3: 检查文件系统
- [ ] 验证 PNG 文件是否存在

## Root Cause (待定)

## Fix Applied (待定)
