# 热模型与热电约束升级设计（子项目3）

## 1. 范围与目标

本规格聚焦路线顺序中的第 3 步：先完成热模型与热电约束升级，再进入多目标函数升级与对比实验。

本阶段目标：

1. 构建“可插拔接口 + 标准版半经验模型”的热模型能力。
2. 在启发式与 CP-SAT 两层同时接入热约束，保证行为一致。
3. 建立分层温度阈值机制：危险阈值硬约束 + 预警阈值软惩罚。
4. 为后续多目标归一化、对比实验、星上实时规划预留可复用热特征与接口。

非目标：

1. 本阶段不实现 GA 对比实验入口（路线第 1 步）。
2. 本阶段不实现完整多目标函数归一化与动态权重切换（路线第 2 步）。
3. `payload_mix_factor` 与 `eclipse_factor` 仅保留接口占位，不参与当前计算。

## 2. 已确认决策

本次会话已确认并冻结的关键口径：

1. 路线顺序：3 -> 2 -> 1 -> 4。
2. 模型范式：可插拔接口 + 标准版先落地，扩展项占位。
3. 阈值策略：
   - `danger_threshold`：硬约束。
   - `warning_threshold`：软惩罚。
4. 时间步长：新增独立配置 `runtime.thermal_time_step`。
5. 参数策略：默认值 + 配置覆盖。
6. 约束接入层：启发式 + CP-SAT 同时接入。
7. CP-SAT 热约束表达：线性近似约束。
8. 连续超温口径：
   - 瞬时温度不得超过危险阈值。
   - 连续预警时长不得超过 `max_warning_duration`。
9. 产热并发非线性：二次项 `lambda_concurrency * concurrency^2`。
10. 散热项：线性散热 + 姿态相关扰动挂点。
11. 初始温度来源：上一轮状态优先，缺失回退配置值。

## 3. 模型形式

### 3.0 变量单位与取值域（第一版固定口径）

| 变量 | 含义 | 单位 | 取值范围 |
| --- | --- | --- | --- |
| `temperature` (`T`) | 当前温度 | ℃ | 实数 |
| `env_temperature` (`T_env`) | 环境参考温度 | ℃ | 实数 |
| `power_total` (`P`) | 总功耗 | W | `P >= 0` |
| `cpu_util` (`u_cpu`) | CPU 利用率 | 比例 | `[0,1]` |
| `gpu_util` (`u_gpu`) | GPU 利用率 | 比例 | `[0,1]` |
| `memory_util` (`u_mem`) | 内存利用率 | 比例 | `[0,1]` |
| `concurrency` | 同一热步内并发任务数 | 个 | 非负整数 |
| `attitude_switch_rate` | 姿态切换率 | 次/秒 | `>=0` |
| `thermal_time_step` (`Δt`) | 热模型离散步长 | 秒 | `>0` |

系数量纲约定：

1. `a_p` 的量纲为 `℃/(W*秒)`。
2. `a_c` 的量纲为 `℃/(个*秒)`。
3. `lambda_concurrency` 的量纲为 `℃/(个^2*秒)`。
4. `a_cpu`, `a_gpu`, `a_mem` 的量纲为 `℃/秒`。
5. `a_s` 的量纲为 `℃/次`。
6. `k_cool` 的量纲为 `1/秒`。
7. `b_att` 的量纲为 `℃/秒`。

### 3.1 状态变量（标准版）

第一版采用标准状态向量：

1. `temperature`
2. `power_total`
3. `cpu_util`
4. `gpu_util`
5. `memory_util`
6. `concurrency`
7. `attitude_switch_rate`

扩展占位（暂不启用）：

1. `payload_mix_factor`
2. `eclipse_factor`

### 3.2 离散更新方程（加性一阶）

采用离散热更新：

$$
T_{t+1}=T_t + (Q_{gen}-Q_{cool})\cdot \Delta t
$$

其中：

$$
Q_{gen}=a_p P + a_c\,concurrency + \lambda\,concurrency^2 + a_{cpu}u_{cpu}+a_{gpu}u_{gpu}+a_{mem}u_{mem}+a_s\,switch\_rate
$$

$$
Q_{cool}=k_{cool}(T_t-T_{env}) + b_{att}\,attitude\_cooling\_disturbance
$$

说明：

1. `attitude_cooling_disturbance` 第一版保留接口，默认 0。
2. 参数 `a_*`, `lambda`, `k_cool`, `b_att` 提供默认值，允许配置覆盖。

## 4. 约束定义

### 4.0 时间离散与换算规范

现有调度器以 `runtime.time_step`（秒）离散时间轴，热模型采用独立 `runtime.thermal_time_step`（秒）。

统一映射规则：

1. 对调度离散索引 `s`（从 0 起），其物理时间为 `t_sec = s * time_step`。
2. 热模型索引定义为：
   $$
   h = \left\lfloor \frac{t_{sec}}{thermal\_time\_step} \right\rfloor
   $$
3. `time_step` 不能整除 `thermal_time_step` 时，仍使用 `floor` 规则；同一 `h` 内的多个调度片共享热状态。
4. 连续时长一律以物理秒为真值，并同时输出折算步数 `duration_steps = ceil(duration_sec / thermal_time_step)`。

### 4.1 分层阈值

1. 硬约束：
   $$
   T_t < danger\_threshold
   $$
2. 软约束：
   $$
   warning\_threshold \le T_t < danger\_threshold
   $$
   对应递增惩罚。
3. 连续预警约束：
   连续预警时长不得超过 `max_warning_duration`。

连续预警判定（统一算法）：

1. 生成 `warning_flag[h] = 1` 当且仅当 `warning_threshold <= T_h < danger_threshold`。
2. 当 `warning_flag[h]` 从 `0->1` 开启一段；遇到 `1->0` 关闭一段。
3. 单段时长 `seg_duration_sec = seg_len * thermal_time_step`。
4. 约束条件：`seg_duration_sec <= max_warning_duration`。
5. 仅当温度降到 `< warning_threshold` 才视为打断连续段。

### 4.2 启发式接入

启发式在尝试放入候选任务时，先做热状态滚动预测：

1. 预测新增任务后的温度轨迹。
2. 若违反硬约束，任务直接判不可行。
3. 若触发软约束但不触发硬约束，写入惩罚分并参与排序比较。

软惩罚第一版固定形式：

$$
penalty_h = w_{temp}\cdot \max(0, T_h-warning\_threshold)
$$

$$
thermal\_penalty\_total = \sum_h penalty_h
$$

启发式排序使用 `base_score - alpha_thermal * thermal_penalty_total`。

说明：连续预警时长超限在第一版按硬约束处理，不转化为软惩罚项。

### 4.3 CP-SAT 接入（线性近似）

在 CP-SAT 中采用线性热代理约束：

1. 为时间片或任务段构建线性温度上界近似。
2. 第一版固定采用“三段分段线性上界”近似 `concurrency^2`。
3. 保证硬约束可被 SAT 线性求解器处理，不引入非线性原语。

第一版线性化模板（固定）：

1. 并发变量 `c_h` 取值域 `[0, C_max]`。
2. 断点取 `0, c1, c2, C_max`，其中 `c1 = floor(C_max/3)`, `c2 = floor(2*C_max/3)`。
3. 预计算 `q(c)=c^2`，对每段构造弦线 `line_i(c)=m_i * c + b_i`（弦线位于函数上方）。
4. 引入线性代理变量 `q_proxy_h`，添加约束 `q_proxy_h >= line_i(c_h)`（对所有段同时生效）。
5. 热生成项使用 `lambda_concurrency * q_proxy_h`，确保保守高估，不会低估热生成。
6. 第一版以可行性优先，允许保守上界，不要求与仿真严格贴合。
7. 小并发上界退化规则（必须实现）：
   - 当 `C_max < 3` 时，不使用三段方案。
   - 改用单段保守上界：`q_proxy_h >= C_max * c_h`。
   - 当 `C_max >= 3` 时，使用三段方案。

连续预警在 CP-SAT 的线性建模（第一版固定）：

1. 定义二值变量 `w_h` 表示热步 `h` 处于预警区间。
2. 用 Big-M 将 `w_h` 与温度区间绑定（`warning_threshold <= T_h < danger_threshold`）。
3. 设 `Lmax = floor(max_warning_duration / thermal_time_step)`。
4. 对任意长度 `Lmax+1` 的滑动窗口施加：
   $$
   \sum_{k=h}^{h+Lmax} w_k \le Lmax
   $$
5. 该约束保证不存在长度大于 `Lmax` 的连续预警段。

## 5. 配置设计

新增（或扩展）运行配置字段：

1. `runtime.thermal_time_step`
2. `runtime.initial_temperature_fallback`
3. `runtime.thermal_initial_source`（`last_state_first`/`config_only`）
4. `runtime.replan_state_max_age_sec`

新增（或扩展）约束配置字段：

1. `constraints.thermal.warning_threshold`
2. `constraints.thermal.danger_threshold`
3. `constraints.thermal.max_warning_duration`
4. `constraints.thermal.env_temperature`
5. `constraints.thermal.coefficients`（`a_p`, `a_c`, `lambda_concurrency`, `a_cpu`, `a_gpu`, `a_mem`, `a_s`, `k_cool`, `b_att`）
6. `constraints.thermal.payload_mix_factor`（占位）
7. `constraints.thermal.eclipse_factor`（占位）

默认值策略：全部给出默认值，并允许配置覆盖。

兼容迁移策略（与现有扁平配置共存一版）：

1. 读取优先级：`constraints.thermal.*` > 历史扁平字段 > 默认值。
2. 若同时存在新旧字段且值冲突：采用新字段，并输出弃用告警。
3. 在本阶段保留历史扁平字段兼容；下一里程碑再移除。

旧字段到新字段映射（第一版）：

1. `constraints.thermal_capacity` -> `constraints.thermal.danger_threshold`
2. `constraints.thermal_warning_capacity`（若存在） -> `constraints.thermal.warning_threshold`
3. 未提供旧字段映射时，使用新字段默认值。

冲突告警触发条件：

1. 同时出现新旧映射字段且数值不一致。
2. 输出告警消息，内容至少包含冲突键名与最终采用值。

## 6. 接口与模块边界

### 6.1 可插拔接口

新增热模型接口（示意）：

1. `ThermalModelProtocol`
2. `update(state, features, dt) -> next_state`
3. `estimate_penalty(trace, thresholds) -> penalty`

第一版实现：

1. `SemiEmpiricalThermalModelV1`
2. `NoOpThermalModel`（用于回退或对比）

### 6.2 状态来源

新增温度初值读取逻辑：

1. 尝试读取上一轮状态输出中的温度。
2. 若缺失，则使用配置回退值。

读取链路固定为：

1. `last_state.temperature`（存在且时间戳有效）
2. `runtime.initial_temperature_fallback`

若 `last_state` 缺失、键不存在或时间戳超出重规划容忍范围，视为无效并回退。

状态时效判定（固定）：

1. 配置键：`runtime.replan_state_max_age_sec`，单位秒。
2. 判定公式：
   $$
   age\_sec = current\_time\_sec - last\_state\_timestamp\_sec
   $$
   当 `age_sec <= replan_state_max_age_sec` 才认为状态有效。

## 7. 输出与可观测性

本阶段必须输出热相关观测指标：

1. 峰值温度 `peak_temperature`
2. 最小热裕度 `min_thermal_margin`
3. 预警时长 `warning_duration`
4. 连续预警最大段长 `max_continuous_warning_duration`
5. 热惩罚累计 `thermal_penalty_total`

这些指标将作为下一阶段多目标归一化与算法对比实验的输入。

## 8. 风险与应对

1. 风险：CP-SAT 线性近似与启发式热仿真不一致。
   - 应对：统一参数源与时间步长；建立一致性回归测试。
2. 风险：参数默认值不合理导致温度发散。
   - 应对：加入参数边界校验与温度上限保护。
3. 风险：连续预警约束在不同时间粒度下含义偏移。
   - 应对：强制绑定 `thermal_time_step` 与时长换算逻辑。

## 9. 验收标准

1. 启发式与 CP-SAT 在热硬约束上都能阻止危险超温解。
2. 预警区间行为可观测，且连续预警时长约束生效。
3. 配置缺省可运行，覆盖后行为按预期变化。
4. 热指标输出完整，可直接供下一阶段目标函数升级复用。
5. `payload_mix_factor` 与 `eclipse_factor` 占位存在且不影响当前计算路径。

最小测试矩阵（必须新增自动化用例）：

1. 单位与范围校验：非法 `thermal_time_step<=0`、阈值倒置、系数越界应报错。
2. 时间换算一致性：`time_step` 与 `thermal_time_step` 非整除场景下，启发式与 CP-SAT 使用同一 `h` 映射。
3. 连续预警边界：恰好等于 `max_warning_duration` 允许，超过最小一个热步即触发硬约束。
4. 硬约束回归：任一时刻 `T_h >= danger_threshold` 的解必须不可行。
5. 软惩罚回归：同可行解中更高温轨迹应产生更大 `thermal_penalty_total`。
6. 配置兼容回归：仅旧字段、仅新字段、新旧混用三种配置均可加载并行为可预期。
7. CP-SAT 线性化保守性：任意 `c_h` 下 `q_proxy_h >= c_h^2`，不得出现热生成低估。
8. 冲突告警回归：新旧字段冲突时，必须记录告警且采用新字段值。
9. 小并发退化回归：`C_max<3` 时自动切换单段上界方案且模型可求解。
10. 状态时效回归：`last_state` 过期后必须回退到 `initial_temperature_fallback`。
