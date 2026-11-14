# 320×240 下远景模糊：链路定位分析与暂缓决策

> 日期：2026-10-16 ｜ 状态：**纯调研结论，未做任何代码改动**
> 决策：暂不推进画质改进——当前优先级是低时延 + 高帧率（WebRTC 主路 18ms/60FPS 成绩不为画质让路）
> 关联：[webrtc-browser-render-optimization.md](webrtc-browser-render-optimization.md)（时延/帧率线）、[webrtc-e2e-latency.md](webrtc-e2e-latency.md)

---

## 1. 现象

模拟器相机分辨率 320×240 时，网页端画面中远处的树非常模糊，车靠近一段距离后**突然**变清晰。问：原因在 Unity 模拟器侧，还是 WebRTC 侧？

## 2. 结论（TLDR）

**不是单一环节，且严格说既不全是 Unity 也不全是 WebRTC——链路上有三层有损环节，每一层都最先丢弃"远处树木"这类高空间频率细节：**

1. Unity 以 320×240 渲染（`render_img_w/h` 覆盖了 640×480 默认值）→ 远处树先天只有几十像素高，细节采样不足；
2. 模拟器→车端走 **JPEG 传输，质量 75**（`CameraSensor.cs` 的 `JPG_QUALITY`）→ JPEG q75 恰好以抹高频见长；
3. 车端→浏览器 **VP8 1.5 Mbps CBR 钉死，60fps** → 每帧仅 ~3.1KB ≈ **0.33 bit/像素**，高频细节再被量化掉一轮。

另有第四个次要因素：前端显示宽度钳制 320~640px，320 源在宽容器下被拉伸至多 2× 显示，整幅再加一层软。

已在模拟器源码（sdsandbox）中 grep 确认**没有景深（DoF）、雾、后处理脚本**——这不是 Unity 镜头效果，纯粹是信息被逐层丢弃。与此前优化的浏览器呈现/时延线无关（那是帧率/时延问题，不是静态清晰度问题）。

## 3. 原理：为什么"远糊近清"是有损压缩的签名

远处的树，枝叶特征在画面里不足 1~2 像素宽——**高空间频率**内容。JPEG 和 VP8 都基于 8×8 DCT + 量化，**量化矩阵先清零的就是高频系数**：代表细碎枝叶的高频分量被丢弃，整块糊成涂抹状。车靠近后同样的枝叶变成 5~10 像素宽，能量落入低频段、回到量化器保留范围内——于是"突然"清晰。这个突变的过渡正是有损压缩的特征；若是纯分辨率采样不足，更多表现为锯齿/摩尔纹而非平滑模糊。

## 4. 链路逐层事实（含代码位置，2026-10-16 核实）

| # | 环节 | 代码位置 | 实际参数 | 对远景细节的影响 |
|---|---|---|---|---|
| 1 | Unity 相机渲染 | `~/Dev/DKC/mycar/myconfig.py:16` `"render_img_w": 320, "render_img_h": 240` | 渲染目标 320×240（覆盖 dgym 默认 640×480） | 远处树仅几十像素高，mipmap 平均化，细节先天不足 |
| 2 | 模拟器 JPEG 编码 | `~/Dev/DKC/sdsandbox/sdsim/Assets/Scripts/camera/CameraSensor.cs:26` `const int JPG_QUALITY = 75`（stb 工作线程与 Unity 主线程回退两路一致） | JPEG 质量 75 | q75 优先抹 8×8 块内高频系数 |
| 3 | socket 传输 + 解码 | `~/Dev/DKC/GymDonkeyCar/gym_donkeycar/envs/donkey_sim.py` `cv2.imdecode(np.frombuffer(jpg_bytes…), cv2.IMREAD_COLOR)` | 无损（解码） | — |
| 4 | VP8 编码 | `donkeycar/parts/webrtc_encoder.py:38` `DEFAULT_VIDEO_BITRATE = 1500000`；`minrate/maxrate/bufsize` 全钉在 target（CBR），`deadline=realtime` 最快档 | 1.5 Mbps @ 60fps → 每帧 ~3.1KB ≈ **0.33 bpp** | 偏紧；高频细节再量化掉一轮 |
| 5 | 浏览器显示 | `web_ui/frontend/src/components/drive/VideoStream.tsx:13-14` `DRIVE_VIDEO_MIN_WIDTH_PX = 320 / MAX = 640` | 320 源最多拉伸 2× 显示 | 整幅均匀变软（与距离无关） |

码率数学：1.5 Mbps ÷ 60 fps = 25 kbit/帧；25,000 bit ÷ 76,800 px（320×240）≈ **0.33 bit/像素**。对含细碎远景的内容，VP8 舒适区一般要 0.5~1 bpp。

排除项：`grep -rin "DepthOfField|PostProcess|fog|antiAliasing|aniso"` sdsandbox Scripts 无命中（场景资产层面理论上仍可能有，但 sdsandbox 是素场景，基本可排除）。

## 5. 归属判别实验（**全部未实施**，按性价比排序）

| # | 实验 | 做法 | 判读 |
|---|---|---|---|
| 1 | **车端落盘中间帧（一刀两断）** | 把 `preview_frame`（imdecode 之后、VP8 之前）存 PNG，同时截浏览器画面对比 | PNG 远处已糊 → 模拟器侧（渲染分辨率 + JPEG q75）；PNG 清晰 → VP8 侧 |
| 2 | 提高码率 | `DRIVE_WEBRTC_VIDEO_BITRATE=3000000` 重启后端 | 远处清晰度改善 → VP8 占比大 |
| 3 | 提高 JPEG 质量 | `CameraSensor.cs` `JPG_QUALITY` 75→90 重编模拟器 | 改善 → JPEG 层占比大 |
| 4 | 提高渲染分辨率 | `render_img_w/h` 改 640×480（前端钳 640 刚好 1:1） | 改善 → 采样极限占比大 |
| 5 | 粗判 | 直接看模拟器本机游戏窗口同距离的树 | 仅参考（窗口分辨率≠相机分辨率） |

预判：底子是 320×240 采样极限，JPEG q75 和 VP8 0.33bpp 各再抹一层；三者比例做一次实验 1 即可定性。

## 6. 暂缓理由：画质 knob 全部与时延/帧率冲突

| 改进方向 | 画质收益 | 时延/帧率代价 |
|---|---|---|
| render_img 320→480/640 | 采样极限翻倍 | dgym 内实测注释：更高渲染分辨率不增帧率，只多烧模拟器 CPU、放大每帧 JPEG 编解码与 socket 传输耗时（**真实体感时延变差**） |
| JPG_QUALITY 75→90 | JPEG 层高频保留 | 模拟器编码耗时与帧体积上升 → socket 传输耗时上升 → 时延变差 |
| 码率 1.5M→3M | VP8 层高频保留 | VP8 软编耗时略增、网络占用翻倍（局域网内影响小，但违背"不为画质让路"） |
| 60→30fps 换每帧 bits 翻倍 | 远景（时域变化小）大幅受益 | **直接砍半帧率，与 60FPS 目标正面冲突，排除** |

当前主线成绩（原生 120Hz 屏 17.4ms/60FPS）刚达成且稳定，上述每一项都会往回退，故全部搁置。**此文档只记录结论与判别路径，等未来优先级变化时从实验 1 开始。**

## 7. 遗留

- 实验 1~4 均未跑，三层占比未定量。
- 若未来推进：先做实验 1 定性，再按"代价最小收益最大"排序（大概率是码率 → JPEG 质量 → 渲染分辨率的顺序，视实验结果调整）。
- 前端 2× 拉伸变软是均匀的、与距离无关，不解决"远糊近清"主诉，不列入改进项。
