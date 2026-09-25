# CPU 调频模式与过热关机防护

> 适用机型：Rhino Pi A1（QCS6490，8 核 1+3+4 三集群）
> 依据：[APLUX《CPU 性能设置》文档](https://docsv2.aidlux.com/hardware/rhino-pi/rhino-pi-a1/os/ubuntu/system-use/performance) + 2026-09 实机排查
> 结论先行：**保持 `schedutil`，通过 `scaling_max_freq` 封顶控温；不要用 powersave（不可用且会卡），不要常驻 `performance`（会热关机）。**

## 1. 当前调频状态

```bash
cat /sys/devices/system/cpu/cpufreq/policy*/scaling_governor   # 均为 schedutil
```

| policy | 核心范围 | 集群 | 频率范围 | 驱动 |
|---|---|---|---|---|
| policy0 | CPU 0–3 | 小核 ×4 | 300 MHz – 1.96 GHz | qcom-cpufreq-hw |
| policy4 | CPU 4–6 | 大核 ×3 | 691 MHz – 2.4 GHz | qcom-cpufreq-hw |
| policy7 | CPU 7 | 超大核 ×1 | 806 MHz – 2.71 GHz | qcom-cpufreq-hw |

本机内核实际支持的策略只有 4 种：`ondemand userspace performance schedutil`。
**`powersave` 未注册**（高通驱动没提供），强行写入报 Invalid argument；`conservative` 同样不可用。

## 2. 为什么不用 powersave / 不常驻 performance

- **powersave**：行为是锁死最低频（300/691/806 MHz）。交互、编译、NPU 链路的 CPU 侧预处理/后处理都会明显卡顿，端到端延迟恶化一个数量级；且总能耗未必降低（任务被拖得更久）。防过热的效果用封顶方案可无损达到。
- **performance**：锁最高频，绕过 schedutil 的自然回落，长时间满载下热区会持续爬升直至 critical 关机。只在短时基准测试前临时切换，测完立即切回 schedutil。

## 3. 过热关机机理

系统热保护是分级自动的，正常情况无需干预：

| 温度 | 动作 |
|---|---|
| 95–110 °C | 各区 passive 点触发：cpufreq cooling 逐档降频、idle 注入，变慢但不关机 |
| 118 °C | **critical：立即热关机**（"突然关机"即击穿此阈值） |

另注意电源侧保护：PMIC `pm8350c-bcl`（电流/电压保护）触发同样是瞬间断电，体感与热关机无异。之前能关机，大概率是散热环境极端（外壳封闭/无风）叠加持续满载，被动降频追不上发热。

当前健康参考值（轻载）：CPU 各区 49–53 °C，NPU（nspss0/1）48–49 °C，skin 48 °C。

## 4. 推荐控温方法：schedutil + scaling_max_freq 封顶

轻中负载不受影响、只在冲高频时被限制；峰值发热约降 30–40%（功耗近似随频率平方），单核速度仅损失 10–20%。

```bash
# 例：大核封 2.05 GHz、超大核封 2.4 GHz（各集群次高档），小核不动
echo 2054400 | sudo tee /sys/devices/system/cpu/cpufreq/policy4/scaling_max_freq
echo 2400000 | sudo tee /sys/devices/system/cpu/cpufreq/policy7/scaling_max_freq

# 恢复满频
echo 2400000 | sudo tee /sys/devices/system/cpu/cpufreq/policy4/scaling_max_freq
echo 2707200 | sudo tee /sys/devices/system/cpu/cpufreq/policy7/scaling_max_freq
```

可用的频率档位（KHz）：

```bash
cat /sys/devices/system/cpu/cpufreq/policy4/scaling_available_frequencies
# 小核 policy0：300000 ~ 1958400；大核 policy4：691200 ~ 2400000；超大核 policy7：806400 ~ 2707200
```

压力测试前的组合操作：

```bash
# 控温封顶
for p in policy4 policy7; do ...; done   # 见上方封顶命令
# 测完恢复
for p in policy4 policy7; do ...; done   # 见上方恢复命令
```

如需短时定频测试（临时切 performance，测完必须切回）：

```bash
for p in policy0 policy4 policy7; do
  sudo bash -c "echo performance > /sys/devices/system/cpu/cpufreq/$p/scaling_governor"
done
# 测完恢复
for p in policy0 policy4 policy7; do
  sudo bash -c "echo schedutil > /sys/devices/system/cpu/cpufreq/$p/scaling_governor"
done
```

## 5. 监控命令

```bash
# 重点看 CPU 集群（zone10/11）与 NPU（zone23/24）温度，单位 m°C
watch -n2 "cat /sys/class/thermal/thermal_zone1{0,1,2,3,4}/temp"

# 温控是否已在降频（cur_state > 0 表示 thermal 引擎已介入压频）
for c in /sys/class/thermal/cooling_device{8,9,10}; do
  echo "$(cat $c/type): $(cat $c/cur_state)/$(cat $c/max_state)"
done

# 当前实时频率
cat /sys/devices/system/cpu/cpufreq/policy*/scaling_cur_freq
```

## 6. 与本项目（DonkeyDrift / NPU 推理）的关联

- NPU invoke 本身不耗 CPU，但图像预处理/后处理在 CPU 上跑，CPU 降频会直接抬高端到端延迟；
- 做延迟基准测试时：先封顶控温再跑，避免长时间满载把热区推到 95 °C 以上引发被动降频，导致前后数据不可比；
- 车辆实跑（DonkeyCar 场景）外壳封闭，建议**常驻封顶**（大核 2054400 / 超大核 2400000），实跑中 thermal passive 介入即意味着性能抖动。
