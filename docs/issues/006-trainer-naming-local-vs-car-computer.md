# Issue 006: Trainer 页面「本机」与「车载电脑」命名颠倒

- 状态: open
- 记录日期: 2026-09-04
- 页面: Trainer（训练器）→ 训练目标切换（本机 / 车载电脑 / 云端）
- 类型: bug（术语/文案）

## 现象

Trainer 页面顶部三档训练目标中，「本机」实际指通过 SSH 连接的远程电脑（界面要求填写 SSH 主机/用户名/密码，文案为『填写这台电脑的 SSH 连接信息』），而「车载电脑」实际指运行 Web UI 的本机/车端。命名与实际含义颠倒。

**已确认的最终命名（2026-09-04）：「本机」→「局域网主机」（Lan Host），「车载电脑」→「本机」（Local Host）。** 即：

| 内部枚举 | 含义 | 旧 zh / en | 新 zh / en |
|---|---|---|---|
| `mypc` | SSH 连接的远程开发电脑 | 本机 / This Computer | **局域网主机 / Lan Host** |
| `local` | 运行 Web UI 的车端本机 | 车载电脑 / Car Computer | **本机 / Local Host** |
| `online` | 云端 | 云端 / Cloud | 不变 |

## 改动范围（调研结果）

用户可见文案集中在一处 i18n 文件，组件层全部通过 key 取词，改动面收敛：

1. **i18n（核心）** `web_ui/frontend/src/i18n/messages/trainer.ts`
   - zh：`:6-8` `tabMyPc: '本机'` / `tabLocal: '车载电脑'` / `tabCloud: '云端'`；`:10-12` `startMyPcTraining: '在本机上训练'` / `startLocalTraining: '在车载电脑上训练'`；`:67-68`、`:72-73`、`:80`、`:88` 等相关文案
   - en：`:96-98` `This Computer` / `Car Computer` / `Cloud`，`:100-102`、`:157-178` 等
2. **前端测试**：`web_ui/frontend/src/components/trainer/ModeTabs.test.tsx:29-31,45,47` 硬编码断言 `'本机'` / `'车载电脑'` / `'云端'`，必须同步。
3. **后端直出文案**（不走 i18n）：`web_ui/backend/mypc_probe.py:296` `环境就绪，可以开始本机训练。`、`:202` 建议文案；对应测试 `web_ui/backend/tests/test_trainer_mypc.py:82`。
4. **文档**：`docs/guide/web-drive-console-user-guide.md:250-252` 「## 本机训练（This Computer）」整节术语需梳理。

不应改的：内部枚举值 `mypc` / `local`（`ModeTabs.tsx:4`）、API 路径 `/train/mypc`、`/train/local`、i18n key 名——改动面会扩散到后端 job 管理、测试 mock、E2E。也不应改 `network_utils.py`、`routers/connector.py`、`drive.ts` 等处语义独立的「本机」。

## 修复建议

1. 只改显示字符串：`tabMyPc: 本机 → 局域网主机`（en: `This Computer → Lan Host`）、`tabLocal: 车载电脑 → 本机`（en: `Car Computer → Local Host`），并同步 `startMyPcTraining`（在局域网主机上训练 / Train on Lan Host）/ `startLocalTraining`（在本机上训练 / Train on Local Host）/ `myPcTraining` / `myPcFirstUseHint` 等派生文案。
2. 同步第 2、3、4 类位置的测试与文档。
3. 在 `trainer.ts` 文件头加注释说明 key 名与显示语的映射约定（改名后 `startLocalTraining` 实际指「本机」，key 名与文案相反，属可接受的内部债务）。

## 风险提示

- CHANGELOG 显示该命名已**翻转过三次**（`:1455-1456`、`:1378-1380`、`:1369-1371`，上一轮明确论证过「本机=SSH 所在机、车载电脑=跑后端的机器」）。本次已确认为第四次调整（2026-09-04：本机→局域网主机、车载电脑→本机），实施时必须把最终约定写进用户手册 `docs/guide/web-drive-console-user-guide.md` 并在 CHANGELOG 记录视角约定（以车上操作视角为准：「本机」= 手边这台跑 Web UI 的车端电脑），避免再次翻转。
