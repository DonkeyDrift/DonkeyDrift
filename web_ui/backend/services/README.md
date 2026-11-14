# services/ 服务层（Phase 1 重构目标）

本目录用于存放从 `routers/` 抽取的业务逻辑，与 FastAPI 路由解耦。

## 当前状态

`harness_updater.py` 是从 `routers/harness_updater.py` 抽取的业务逻辑参考实现（1009 行）。

**尚未集成到 router**：测试大量 monkeypatch router 模块的内部函数（`_current_donkeydrifter_version`、`check_harness_updates` 等），直接抽取会导致 21 个测试失败。需要先重构测试（改为 monkeypatch service 模块或使用依赖注入），再切换 router 导入。

## 重构教训（round 8）

1. **测试侵入性**：现有测试通过 `monkeypatch.setattr(hu, "func_name", mock)` 直接替换 router 模块的内部函数。抽取到 service 后，这些 monkeypatch 目标消失，导致 `AttributeError`。

2. **正确做法**（下一轮）：
   - 方案 A：测试改为 monkeypatch `services.harness_updater` 模块（需修改 ~21 个测试）
   - 方案 B：router 用 `from services.harness_updater import *` 并显式 re-export 被 monkeypatch 的函数（已尝试，但内部函数太多）
   - 方案 C：依赖注入 — router 构造时接收 service 实例，测试注入 mock（最干净但改动最大）

3. **推荐路径**：先做方案 A（改测试），再切换 router；或等 Phase 2 统一重构测试基础设施。

## 文件清单

- `harness_updater.py` — Harness 下载/安装/更新/OTA 业务逻辑（参考实现）
- `__init__.py` — 包初始化

## 参考

- `routers/harness_updater.py` — 当前生产代码（1121 行，路由+业务耦合）
- `tests/test_harness_updater.py` — 22 个测试（大量 monkeypatch 内部函数）
- `docs/plan/harness-updater-design.md` — 设计文档
