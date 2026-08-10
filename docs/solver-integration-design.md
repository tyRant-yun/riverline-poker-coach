# Solver Integration Design Review

版本：v1 · 日期：2026-08-10 · 状态：已评审（只读设计，未实现）

目标：完成一次 **Coach Spot → Solver → Coach Answer** 的完整闭环设计——把成熟求解引擎作为**计算引擎依赖（sidecar）**接入现有 Poker Coach，而不是自研 CFR。本文档只读分析现有仓库架构，确定模块落点、`ScenarioSpec → SolverSpot` 字段映射、以及 `SolveResult` 如何被现有回答流程消费。不含任何代码改动。

## 1. 选型结论（用户已确认，2026-08-10）

| 角色 | 选择 | 依据 |
|---|---|---|
| 求解引擎 | **`b-inary/postflop-solver`（Rust，AGPL-3.0）** | 现成 DCFR；OOP/IP 加权 range、board、pot/effective stack、rake、自定义下注尺度、flop/turn/river、exploitability、combo 级策略/EV/equity、action tree 导航、`memory_usage()` 预估算、多线程/同构压缩；调用流程（`CardConfig+TreeConfig → game → solve → 查询`）与 Adapter 需求天然吻合 |
| 集成形式 | **独立 sidecar 进程/服务**（不 FFI、不嵌入 Python） | 高 CPU/高内存负载与主进程隔离；timeout/kill/内存限制/重启都容易；后续可换引擎（TexasSolver/GPU 后端）而不动上层 |
| B 方案 | TexasSolver（C++，AGPL） | `PokerSolver` 已暴露 `build_game_tree/train/stop/estimate_tree_memory/dump_strategy` 等生命周期接口，sidecar 化最容易；若 postflop-solver 与运行环境冲突则启用 |
| 不采用 | robopoker（MCTS 全家桶）、OpenSpiel（真实求解）、noambrown/poker_solver | 前者过重（abstraction/MCCFR/arena/backend 均用不上）；OpenSpiel 保留为测试工具；poker_solver 至多作为结果验证器（exploitability/best response 参考） |

**许可路径（已确认）**：项目非商用、无收益，采用**隔离服务路径**——AGPL 引擎作为独立进程/HTTP 服务运行，与主项目仅通过 API 交互，主项目保持宽松许可；solver 输出数据（JSON）不属于代码，可自由导入。若未来公开分发或部署给第三方使用，需另行处理 AGPL 义务（用户已知悉）。

## 2. 模块落点（现有仓库架构映射）

新增 `backend/poker_coach/solver/` 包，插在分析核心与策略/教学之间：

```text
ScenarioSpec（domain）
   │  SolverAdapter（solver/adapter.py，双向映射）
   ▼
SolverSpot（solver/types.py，规范请求模型）
   │  SolverClient（solver/client.py，sidecar 提交/轮询/取消/内存预检）
   ▼
Solver Worker / Sidecar（独立 Rust 进程，docker-compose 新服务）
   ▼
SolveResult（solver/types.py，规范结果模型）
   │  校验（复用 solver-import-spec 规则：合法动作重放/频率归一化/死牌过滤）
   ▼
StrategyAnalyzer（solver/analyzer.py，确定性数学：主导动作/混合度/EV 差/价值-诈唬区）
   ▼
StrategyArtifact（solver_backed）+ EvidenceBundle（evidenceId 前缀 solver.*）
   ▼
StrategyMatch（EXACT/COMPATIBLE → can_quote_frequencies）→ 教师解释（本地/外部）
```

分层边界（镜像现有规则层约束）：**postflop-solver 类型不得泄漏出 `solver/` 适配层**；Coach 领域模型（`ScenarioSpec`/`StrategyArtifact`）是上下层唯一契约。

任务队列：复用 `poker_coach.jobs` 的 Redis 队列与协作式取消标志；SolveJob 生命周期 `QUEUED → RUNNING → SOLVED | FAILED | CANCELLED`，并带 timeout / stop / 内存预检（`memory_usage()` 在真正分配前估算，超过配额直接拒绝并提示降低下注尺度数量或开启 compressed solve，而不是 OOM）。

## 3. `ScenarioSpec → SolverSpot` 字段映射

| SolverSpot（规范请求） | ScenarioSpec 来源 | 说明 |
|---|---|---|
| `game`（NLHE） | `game_variant` | MVP 仅 NLHE（模型已强制） |
| `players`（OOP/IP） | `table_size=2` + `seats[].position` | HU 固定；OOP=非按钮 |
| `street` | `decision_point.street`（flop/turn/river） | 由 `action_history` 重放对齐 |
| `board` | `board` | 空牌面（preflop）本轮不求解 |
| `ranges.oop / ranges.ip` | `hero_range` / `villain_range`（`RangeSpec`） | `combos`（组合+权重）直接映射；`matrix_169` 需展开为组合；死牌 `dead_cards` 同步 |
| `pot` | 重放得到：`PokerKitAdapter.replay_to_decision(...)` 的 pot | 求解点底池（盲注/行动累计） |
| `effective_stack` | `min(seats[].starting_stack)` - 已投入 | HU 下 min 双方剩余 |
| `rake` | `rake_config` | 当前 `no_rake`；postflop-solver 支持，字段保留 |
| `tree`（OOP/IP bet sizes、raise sizes、allin 策略） | `allowed_bet_sizes`（`BetSizeSpec`：`action`/`percent_bps`/`cap`）+ `assumptions.allow_donk`/`allow_raise` | 尺寸百分比 × pot；allin 阈值沿用产品约定 |
| `solve`（目标 exploitability、max iterations） | **不污染 ScenarioSpec**：放 SolveJob 请求参数（新增），`assumptions.solver_version` 记录引擎版本 | 与现有 `simulation_trials/random_seed` 的作业参数模式一致 |

注意：**Coach 牌局模型不直接使用 postflop-solver 类型**——映射全部经由 Adapter（用户强调）。

## 4. `SolveResult` 规范（输出标准化）

```jsonc
{
  "metadata": {"solveTimeMs": 42000, "iterations": 1500, "exploitabilityBb": 0.012, "memoryUsageMb": 4096, "solver": "postflop-solver", "version": "0.14.2"},
  "root": {"availableActions": ["check","bet_33","bet_75","all_in"], "rangeStrategy": {...}, "evBb": 3.1, "equity": 0.572},
  "nodes": [
    {"actionHistory": ["bet_33"], "player": "ip", "pot": 200, "stack": 180, "board": ["Kc","7d","2h"],
     "actions": ["call","fold","raise_60"],
     "hands": [{"combo": "AsKh", "weight": 1.0, "evBb": 4.73, "strategy": {"check": 0.61, "bet_33": 0.27, "bet_75": 0.12}}]}
  ]
}
```

- 原始 solver 输出 **不直接**给 LLM 或教师；先经校验（solver-import-spec 第 4 节全部规则），再经 StrategyAnalyzer。
- `solve_hash`（缓存键）= `f(board, ranges, pot, stack, tree, rake, accuracy)`，写 `strategy_artifacts` 表（新增唯一索引），命中即毫秒级返回，避免重复求解。

## 5. StrategyAnalyzer（确定性转换层，防幻觉的关键）

Solver 输出是数学策略，Coach 需要人类可理解的策略；中间不直接 `SolverResult → LLM`：

| Analyzer 输出 | 计算方式 | 教学消费 |
|---|---|---|
| `primary_action` | 按 combo 频率 argmax | "AK 主要过牌" |
| `mixing_degree` | 主频率与次频率差 | "小注是次要混合策略" |
| `ev_gap` | 主导动作与次优动作 EV 差 | "两者 EV 接近（0.04bb）" |
| `range_bet_frequency` | 全范围加注频率 | "这个牌面整体高频率下注" |
| `combo_bet_frequency` | 单 combo 频率 | 与 hero 底牌直接对应 |
| `value/bluff/check 区域` | EV 分层聚类 | "价值区 vs 诈唬区" |
| `hand_class / draw_class / blocker` | 复用 `analysis/hand.py` 分类 | 与现有 hand 证据对齐 |

消费方：`TeachingToolGateway` 新增只读工具 `get_solver_analysis()`，产出 `EvidenceBundle` 新证据项（`evidenceId` 前缀 `solver.*`，如 `solver.primary_action` / `solver.ev_gap` / `solver.exploitability`）——现有 `validate_evidence_references` 自动覆盖，本地与外部教师均受同一证据边界约束。

## 6. 现有回答流程如何消费 SolveResult（端到端）

```text
用户输入牌局 → ScenarioSpec
  → POST /v1/analysis（现状：metrics/hand/board/equity/range_analysis）
  → 新增 SolveJob 分支：SolverAdapter → SolverSpot → sidecar 求解
  → SolveResult 校验 → StrategyAnalyzer
  → 注册 StrategyArtifact（source_level=solver_backed，license=AGPL 数据记录，creator=solver 名+版本）
  → StrategyCatalog 匹配 EXACT/COMPATIBLE → can_quote_frequencies=True（ADR-0003 门控）
  → TeachingToolGateway.get_solver_analysis() → 教师输出带引用的精确频率/EV
```

- 求解失败/超时/被取消 → 降级为现有 principle-only 教学（与外部教师降级路径同构，用户可见 `degraded`）。
- 同步分析（`/v1/analysis`）不受影响：SolveJob 走既有异步作业模式，不阻塞普通 API。

## 7. 分阶段落地（映射用户五阶段到现有资产）

| 阶段 | 内容 | 现有资产复用 |
|---|---|---|
| 1（spike，不碰 UI） | 固定 HU flop spot（board/pot/stack/ranges/bet sizes 全固定）手工跑通 sidecar：稳定得到 exploitability、range EV、AK/QQ/draw 策略 | docker-compose 新 `solver` 服务；验证 `memory_usage()` 预检 |
| 2 | SolverAdapter 双向映射（ScenarioSpec ↔ SolverSpot；SolveResult → 规范模型） | `analysis/models.py`、`domain/models.py` 已有契约 |
| 3 | 异步 SolveJob：QUEUED/RUNNING/SOLVED/FAILED/CANCELLED + timeout/stop/内存配额/progress | `jobs/` Redis 队列、cancel 标志、配额校验模式 |
| 4 | StrategyAnalyzer → `TeachingToolGateway.get_solver_analysis()` + 证据绑定 | `coach/tools.py`、`teacher.py`、`validate_evidence_references` |
| 5 | `solve_hash` 缓存（命中毫秒级）+ 预求解库（常见 spot 批求入库）；后续 node locking / batch solve | `strategy_artifacts` 表 + 现有注册路径 |

阶段 1 完成后，turn/river 只是输入差异；缓存比 GPU 更值得先投入（用户结论）。

## 8. 风险与边界

- **AGPL 分发义务**：非商用下可接受；若未来公开分发/部署给第三方，需整体评估（隔离服务路径下主项目不受传染，但 sidecar 本身的分发需随附源码）。
- **postflop-solver 已停更**（2024-07 作者转商业）：锁定版本、记录已知限制；出现环境冲突时启用 B 方案（TexasSolver，`PokerSolver` 生命周期 API 现成）。
- **树规模内存爆炸**：`memory_usage()` 求解前预检，超配额直接拒绝并给出压缩/降尺度建议；sidecar 崩溃不影响主进程（进程隔离）。
- **类型不泄漏**：postflop-solver 类型与 TexasSolver 类型都不得越过 `solver/` 适配层（新增约束，与 PokerKit 规则层约束同构）。
- **数据导入不变**：任何路径下 solver 输出 JSON 均可按 `docs/solver-import-spec.md` 导入；导入规范仅补充"AGPL 引擎输出需记录 license 字段"。
