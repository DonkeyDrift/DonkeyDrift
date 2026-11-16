# M4 预注册门(开跑前锁定,不许事后移动;2026-11-03)

- 口径:anchor=line(rl-m4-driveline.json,cte 米制,gain −8.114)+ 课程 ±1.8m/±12°
  + 配方 = M3 获胜配方(state-BC 热启动 --resume + lr 1e-4 + KL 只监控)+
  预算 300k×{7,8,9};held-out = 2 重拉实例 × 12 局/实例/种子,
  spawn seed base 50000+,cte_limit=2.0(米)。
- **门(held-out 三 seed 平均)**:
  - offtrack(cte_limit 出界率)≤ **0.15**;
  - step_budget(跑满 2000 步)局占比 ≥ **60%**。
- 未达 = 如实报告,1M+ 预算决策交回用户(不自行加码)。
- 口径纪律:M3 模型(中央线锚,sim cte 单位)与 M4 模型(行车线锚,米制)
  **不可跨口径对比出结论**;M3 数字仅作历史参照分列。
