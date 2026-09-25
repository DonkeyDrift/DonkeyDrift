# Issue 007: 导入模型报「Request failed with status code 422」，导入后「加载到车端」400

- 状态: fixed（2026-09-22）
- 记录日期: 2026-09-22
- 页面: Trainer（训练）页面
- 类型: bug（两处）

## 现象

1. Trainer「已训练模型」卡片点「导入模型」，选好 .tflite/.h5/.zip 点「导入」，弹窗报
   **「导入失败: Request failed with status code 422」**，模型进不了列表。
2. 模型（含刚导入的）点「加载到车端」（Send 图标），弹窗报
   **「加载失败: model_path 必须是相对路径」**（HTTP 400）。

## 根因分析

### ① 导入 422：axios 实例默认 `Content-Type: application/json` 污染了 multipart 请求体

- `services/api.ts` 的 axios 实例带全局默认头 `Content-Type: application/json`。
- `importModel`/`uploadModelLoss` 用 FormData 上传，原实现依赖 axios「自动」为 FormData
  清掉默认 Content-Type（`resolveConfig` 里 `isFormData → setContentType(undefined)`）。
  这条隐式清理对打包/运行环境敏感：经真实 axios + XHR 全链路复现（非 TestClient），
  默认 json 头会原样发出 → 后端按 JSON 解析 multipart 体 →
  FastAPI 422 `{"detail":[{"loc":["body","file"],"msg":"Field required"}]}`。
- 单测此前整体 mock 了 `services/api`，这条真实链路零覆盖，故未暴露。

### ② 加载到车端 400：前端传绝对路径，后端只收相对路径

- `ModelsList.tsx` 「加载到车端」把列表项的 `m.path`（`list_models` 返回的
  **绝对路径**）直接 POST 给 `/drive/load_model`。
- 该接口的 `_validate_model_path`（issue #003 引入，安全设计）明确**拒绝绝对路径**，
  只接受 `models/` 内的相对路径（如 `./models/foo.tflite`，与 DrivePage 选择器一致）。
- 绝对路径在车端也无法按 `complete.py` 的回退读取逻辑（相对 car 目录）解析。

## 修复

- `web_ui/frontend/src/services/api.ts`：FormData 请求统一加
  `headers: { 'Content-Type': null }`——axios 在序列化阶段丢弃该头，由浏览器/XHR
  生成带 boundary 的 `multipart/form-data`（不能手动设 multipart 值，会丢 boundary）。
- `web_ui/frontend/src/components/trainer/ModelsList.tsx`：加载到车端改传
  `` `./models/${m.name}` ``，与 DrivePage 选择器同约定。

## 测试

- 复现：真实 axios（带默认 json 头）+ FormData + jsdom XHR → 真实 FastAPI 后端，
  修复前 422，修复后 200 且模型出现在列表（端到端验证后已清理，不入套件）。
- 新增回归：`services/apiFormData.test.ts`（2 项，断言两个 FormData 请求都置空
  Content-Type）、`ModelsList.test.tsx`（1 项，断言加载到车端传 `./models/<name>`）。
- 全量：前端 vitest 316 过、`tsc -b` 零错误、`npm run build` 通过；
  后端 `test_trainer_models.py` + `test_drive.py` 45 过。
