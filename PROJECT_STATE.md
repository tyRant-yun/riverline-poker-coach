# PROJECT_STATE

> Riverline 德州扑克 AI 教练（poker-coach-web）项目状态快照。
> 更新日期：2026-08-11。本文件与 AGENT.MD 同级，供任何会话快速恢复上下文。

## 1. 项目概览

浏览器端 NLHE 德州扑克 AI 教练：规则引擎（PokerKit）重放牌局 → 结构化分析（Evidence）→ 教学解释（Coach）→ 练习（Practice）→ 翻后求解（Solver sidecar）。前端 Next.js（静态导出），后端 FastAPI + SQLite/PostgreSQL + Redis 队列。

## 2. 当前进度（全部完成 ✅）

| 阶段 | 内容 | 提交 |
|---|---|---|
| F1–F4 | 前端 V2：组件化、三栏 AppShell、Solver UX、座位就绪 | c3c9b9f … ed3e4e9 |
| verify | hermes verify recipe 修复（cmd 引号 set 清 PYTHONPATH） | 6ef18d0 |
| 8A | Schema v2：tableSize 2–8、knownHoleCardsBySeat/rangesBySeat、位置推导、v1→v2 归一化 | 2b4eb3a |
| 8B | PokerKit 多人重放：N 人状态、盲注/ante、边池、分池、摊牌 | 2043e33 |
| 8C | 多way 分析：equityBySeat、potOddsBySeat、activePlayerCount | 27435fc |
| 8D | 8-max preflop knowledge：11 个 RFI/defend/vs-3bet 定性 artifacts | 05c3cb4 |
| 8E | HU solver bridge：决策点 2 活玩家即可求解、有效筹码、bunching 记录 | 3898f50 |
| 79bff76 | street 派生修复（按已发牌面而非 street_index） | 79bff76 |
| UX | 52 张选牌器、复盘模式（只填自己手牌）、提亮 token、使用说明 | a56e5db |
| Fresh | **全新一把**默认起点：0 输入/0 行动/只有盲注（POT 150）+ 测试基建加固 | 6ea3498 |
| Closure | 收口轮：multiway MC 无偏采样（Exact↔MC parity）、fresh-hand 前端 null 契约+E2E、solver rangesBySeat 桥、seat-based 前端状态、domain 校验收紧、CI vitest | e0c2908 … 79a8437 |
| UI-P1 | Hand Lab 前端精修（不推翻三栏）：BB 金额层+单位切换（默认 BB）、board 未发位=弱 empty slot（非 card-back）、seat/action 层级（position 优先+HERO pill+actor ring、call/raise 主蓝）、ScenarioEditor cards 单列+复盘两行+选牌按钮堆叠、History 降密度（title/rev+次级操作）、Range matrix weight 强度+hover+tooltip、Analyze 按钮四级分级+honest 文案、panel 分级、solver disabled 原因 ✓/✗、polling 保留 spot、shell 撑满 1480 宽视口、左栏 min-content 溢出修复（rail 不再压到桌子） | 6903fe8 … d346959 |
| ReviewFix | 复盘模式/任意牌局**打到结束（决策点 1 活玩家）**不再 422：`BasicMetrics.active_player_count` ge=2→ge=1（equity 对单人局不计算；ge=2 仅限 equity 结果模型）；完成牌局 analyze/teaching 正常降级返回 200 | 32073a9 |
| RangeBelief | **Range Belief Engine V1**：combo 级行动条件 Bayesian 更新（newReach=oldReach×P(action\|combo)）、PolicyProvider 抽象（solver/fixture/manual，支持有序 provider 链）、snapshot trace（仅自己行动/deal/prior 生成）、169 派生聚合（质量守恒）、Prior/Current/Δ UI、`POST /v1/ranges/belief` + `POST /v1/ranges/trace`（seat 驱动） | 5fee982 … 7e09eaa |
| RangeBelief V1.1 | **Grounding & Temporal Correctness**：solver job/artifact 绑定 scenario+spot fingerprint、exact policy sequence/actor seat/active seats；jobId 是 grounded 入口，裸 result 仅 `unverified`；target-seat-aware dead cards；`board_at_sequence` 防未来牌泄漏；prior/current union 保留完全淘汰 combo 的负 Delta；single-size off-tree sizing；frontend polling 使用新 artifact，scenario mutation/load/undo/redo 失效旧 solver/belief | local V1.1（2026-08-11） |
| RangeBelief V2.0 | **8-max Preflop Policy（首个窄覆盖版本）**：内置、版本化的 `preflop_policy` provider；仅覆盖 8-max NLHE、全员 100BB、no-ante/no-rake、无前序入池、2.5BB RFI 的 UTG→SB 七个位置。以完整 combo×{Raise,Fold} 策略表重建该行动；节点外一律 `no_policy`，不近似映射。数据为 first-party curated baseline（`confidence=curated`），非 solver export | local V2.0（2026-08-11） |
| TeachingAgent | 外部 teaching agent 接入 compose（LLM env 插值）+ LLM 超时 60→180s（另一 worktree：fix/teaching-agent，已推送 origin） | 694faa2 |
| Hand Review Workbench | **整手逐决策复盘闭环已实现**：真实行动时间线与 actionId 选择、行动前/行动后双游标、按行动者自动 Range Belief（Prior/Current/Δ 与 unavailable/stale）、按 actionId 独立手动 Solver job、grounded SolverAssessment、逐决策教学、整手总结、不确定性与 priority finding 跳转；完成牌局可回看此前决策 | `89842f0`（2026-08-11，QA 收口中） |

分支：`main`（单分支工作流）+ `fix/teaching-agent`（worktree：德州扑克-worktree）。

## 3. 验证基线（2026-08-11，当前 QA 批次快照）

> 以下是本轮已验证的中间快照，不是不可变的最终 release certification。QA-01 仍在并行回归，后续集成可能改变测试文件/用例计数；请以带日期和批次的最新回传为准。

| 门 | 结果 |
|---|---|
| Backend pytest（仓库根，unset PYTHONPATH） | **339 passed + 8 skipped**（live-PG 需 POKER_COACH_TEST_PG_URL 才跑；含 Hand Review、grounded SolverAssessment 与 Range Belief 回归） |
| compileall | OK |
| vitest（frontend） | **29 files / 150 tests**（含行动选择、Range Belief 竞态/stale、按 actionId Solver registry、整手教学与 priority navigation 回归） |
| tsc --noEmit | 0 错误 |
| next build | ✓ |
| Playwright / Hermes | QA-01 并行收口中；本快照不将未在本批次重跑的门当作最终认证 |

## 4. 关键架构约束（不可违背）

- **E2E 即契约**：4+1 条 E2E 断言的钩子必须保留——文案（`规则校验通过…`、`范围已标准化为…`、`3 events`、`已载入…`）、按钮名（`校验场景`、`标准化范围`、`生成分析`、`教学解释`、`保存场景`、`重新分析`、`历史`、`Call 50`、`Check`、`Deal flop`、`提交 Solver`、`编辑范围`）、aria-label（`牌面 1..3`、`169 格范围矩阵`、`AA weight`、`范围侧`、`默认范围`、`教学问题`、`导入 JSON`、`收起范围矩阵`、`combo inspector AKs`）、类名（`.teaching-panel`、`.teaching-summary`、`.revision-row`、`.solve-panel`、`.solve-status`、`.sg-grid`）。注意：`Call 50` 是 Playwright substring 匹配——BB 模式下按钮 aria-label 为 `Call 50（0.5 BB）`（视觉 0.5 BB + `50 chips` 小字），不要改回纯文本 `Call 50`（会与 BB 显示冲突）。
- **后端是规则唯一权威**：前端不伪造规则事实；后端 JSON 字段（camelCase）不改名；solver 数值只重新聚合不重算。
- **不可变语义**：undo/redo、appendAction 的 amount/amountType 映射（call→cost、bet→by、raise_to/all_in→to）。
- **颜色只走 token**：globals.css 的 `--color-*`/`--felt-*` 系列，组件零裸 hex；提亮只动 token。
- **版本锁**：vitest 3.x ↔ vite@^6 ↔ @vitejs/plugin-react@^5；vitest 需 globals:true。
- **pydantic validator 禁原地赋值**：validate_assignment=True 下必须 `model_copy(update=...)` 末尾返回（防无限递归）。
- **复盘/空场景诚实降级**：hero/villain 手牌缺失时 equity 不计算（显式警告），不伪造对手信息；策略匹配与教学（原则性）不受影响。
- **Equity MC 采样契约**：range weights 只在 proposal 中用一次；multiway/pair 必须整元组独立抽样+整体 rejection（接受样本即精确联合分布），禁止逐 seat conditional rejection 或对结果再乘权重。
- **seat 契约**：seat IDs 必须连续 0..table_size-1；knownHoleCardsBySeat 每个 seat 恰 2 张（空数组=缺失）；solver 的 range 真相源是 rangesBySeat（按两个 active seat 解析），Hero/Villain 仅是 Coach 视角。
- **169 Matrix 只是 View（RangeBelief）**：belief 底层状态是具体 two-card combo（canonical key 高位在前、镜像 solver 格式，如 `5c4c`/`2d2c`/`Ac4c`）；禁止把 169 cell 当推理状态。聚合必须质量守恒：`sum(matrix169.probabilityMass) ≈ sum(combo probabilities) ≈ 1`；suit-specific combo（AsKs vs AhKh）保留各自 reach/likelihood 后才聚合到同一 cell。
- **reach 与 probability 分离（RangeBelief）**：`reach`=沿行动序列的未归一化质量，`probability`=归一化条件信念（sum≈1）。likelihood=0 → combo 直接从 belief 移除；全零必须报 `zero_probability_action`（禁止 uniform fallback）。
- **无 policy 不伪造（RangeBelief）**：no_policy / unsupported_action / zero_probability_action 显式降级；内置 `preflop_policy` 只覆盖已声明的 8-max RFI node，其他翻前自身动作仍必须诚实停止（或由 fixture/manual/solver 覆盖）；`available=false` 响应只给 reason + prior，不给假 current。
- **Solver provenance（RangeBelief V1.1）**：生产 grounded policy 必须通过 persisted `jobId`；job 保存 `scenarioFingerprint`、`spotFingerprint`、`policySequence`、`actorSeat`、`activeSeats`、`street`，请求会重建 exact node spot 并拒绝 `solver_artifact_mismatch`。一个 artifact 只覆盖其显式 policy sequence；裸 `source=solver,result` 仅兼容读取并标记 `confidence=unverified`，不得称为 grounded。
- **Policy 抽象（RangeBelief）**：PolicySource 枚举（solver/fixture/preflop_policy/population/heuristic/manual/unknown）；`ActionPolicyProvider.get_action_frequencies(scenario, seatId, sequence, combos)`；API `policy` 支持**有序 provider 链**（如 fixture 覆盖翻前 call + solver 覆盖翻后 bet）；solver 输出零重算——SolverPolicyAdapter 只做 `SolverNode.hands[].strategy → PolicyResult` 映射。
- **Off-tree sizing（RangeBelief）**：显式 ActionMapping 解析 `Bet(250)/Raise(625)/AllIn(9750)/Check/Call/Fold`；off-tree 用 nearest-size（等距取小，确定性），`observedSize/mappedSize/offTree` 进 metadata 与 UI；禁止插值 strategy。
- **Temporal/dead-card semantics（RangeBelief V1.1）**：belief dead cards = visible board at the requested sequence + known hole cards of other seats；target seat own known cards 不删除自己的 strategic range；full imported board 的未来牌只在对应 deal/endpoint 可见。domain range validation 同样按 selected decision node 处理。
- **Delta union（RangeBelief V1.1）**：169 cell 与 combo view 遍历 `union(prior,current)`；current 完全淘汰的 combo 以 probability/reach=0 保留，`comboCount` 表示 union 中 concrete combo 数。
- **Belief seat 驱动（RangeBelief）**：domain/API 全部 seatId 驱动；禁止新增 heroBelief/villainBelief 字段（HU 前端可继续叫 Hero/Villain）。
- **Domain 约束**：RangeSpec 具体 combos 不得包含 selected decision node 上的 visible board 或其他 seats 的 known hole cards；target seat own cards 与 future board cards 不作为该 seat belief 的 blockers；action_history sequence 必须连续从 1 开始；decision_point.actor_seat 必须与 replay 一致。

## 5. PokerKit 地面真值（8B 探针实测）

- 座位映射：`seat = (buttonSeat + playerIndex + 1) % N`，button = player N-1
- 盲注：HU 金额反转（player0=BB 100、player1=SB/BTN 50）；N≥3 player0=SB、player1=BB
- preflop 首动：HU=BTN；N≥3=UTG（seat (button+3)%N）；postflop 每街 SB 先动（fold 则下一活玩家）
- ante：`Automation.ANTE_POSTING` 自动逐人发
- 结算：fold→push=池−赢家自投；all-in/摊牌→push 全池；split→各半；reason 看操作 `HoleCardsShowingOrMucking`

## 6. 运行方式

```bash
# A. compose 全栈（生产形态：redis/postgres/worker/solver-worker）
docker compose up -d --build
# 前端 http://127.0.0.1:3000 · 后端 http://127.0.0.1:8000/health

# B. 本地开发（单机 SQLite + 进程内 worker，不依赖 docker）
# 注意：必须显式置空 DB/Redis URL，否则 .env 会让 uvicorn 挂起在连接
unset PYTHONPATH PYTHONHOME && export POKER_COACH_DATABASE_URL="" POKER_COACH_REDIS_URL=""
py -3.13 -m uvicorn poker_coach.api.app:app --app-dir backend --port 8000
cd frontend && npm run dev -- --hostname 127.0.0.1 --port 3000
```

测试命令（一律 `unset PYTHONPATH`，Hermes 每命令注入 venv 会污染）：
- 后端：`py -3.13 -m pytest -v`（仓库根；-q 管道输出在部分环境被吞，用 -v）
- 前端：`cd frontend && npx vitest run` / `npx playwright test`（E2E 前确认 3000/8000 空闲或 compose down）

Range Belief API 速查：
```bash
# 当前 belief（含 prior/current/delta + matrix169）；policy 可缺省（prior-only）
curl -X POST http://127.0.0.1:8000/v1/ranges/belief -H 'Content-Type: application/json' \
  -d '{"scenario": {...}, "seatId": 6, "policy": {"source": "solver", "jobId": "..."}}'
# 内置翻前 policy：仅 8-max、100BB、no-ante/no-rake、2.5BB RFI（UTG→SB）
curl -X POST http://127.0.0.1:8000/v1/ranges/belief -H 'Content-Type: application/json' \
  -d '{"scenario": {...}, "seatId": 3, "policy": {"source": "preflop_policy"}}'
# 完整 snapshot 链
curl -X POST http://127.0.0.1:8000/v1/ranges/trace -d '{"scenario": {...}, "seatId": 6}'
# policy 支持有序链：[{source: fixture, frequencies}, {source: solver, jobId}]
```

## 6.1 当前 Hand Review Workbench 状态

- **行动与范围**：追加或选择玩家行动后，前端按 actor seat 请求该行动的行动后 Range Belief；`eventSequence` 用于范围 trace，`decisionSequence = eventSequence - 1` 用于行动前分析与 Solver。可用时显示 Prior / Current / Δ；`no_policy`、`unsupported_action`、`zero_probability_action` 等情况保留 Prior 并返回 unavailable，不生成假 Current。旧响应、场景 mutation、load、undo/redo 会被 request gate / fingerprint 标为 stale。
- **逐节点 Solver**：选中历史玩家行动后，显式点击「提交 Solver」才创建该 `actionId` 的 job。gate 为翻后、恰好 2 位 active players、两位范围就绪；job 绑定 `actionId`、`decisionSequence`、`policySequence`、`actorSeat`、`scenarioFingerprint`、`spotFingerprint`。场景或节点变化会使不匹配 job stale；没有整手自动 bulk solve。
- **整手教学**：`POST /v1/hand-reviews` 返回按真实行动顺序的 `decisionReviews`，每个节点拥有行动前快照、独立 EvidenceBundle、rangeUpdate、solverAssessment、teaching 和 warnings；整手结果另有 `wholeHandSummary`、`priorityFindings`、`uncertainty`。priority finding 可用 actionId 跳转回对应决策卡。已完成牌局仍能复盘此前的玩家行动。
- **Solver 状态解释**：`primary`、`mixed`、`rare`、`absent`、`unscored` 是产品展示状态；5% 仅是记录在 metadata 的 `product_interpretation` 阈值。off-tree nearest-size、未验证/不匹配 artifact、无具体 combo、未支持节点均保持 unscored；系统不输出不受支持的 action-specific EV loss。

## 7. 已知边界与剩余风险

- 复盘/空手牌场景：equity 不可用是**有意**的（hero 或 villain 手牌缺失即不计算）；牌局打到结束（决策点 1 活玩家）同样合法降级——`BasicMetrics.active_player_count` 允许 1，equity 不计算（`ge=2` 仅限 equity 结果模型）
- 求解器：仅翻后（flop+）且决策点恰好 2 活玩家；bunching 忽略并记录为近似（`assumptions` 字段）
- 整手复盘已实现，但“有 Solver”不等于“整手所有节点都有 Solver”：Solver 必须按节点显式提交，且只消费与 actionId/节点 fingerprint 匹配的已完成 job；无 job、no-policy、off-tree、provenance mismatch 和不支持节点都保持原则性教学或 unscored。
- 当前 `mixed` 的 5% 边界是产品解释，不是扑克理论阈值；`primary/mixed/rare/absent` 只描述实际行动在已验证 SolverNode 中的频率关系，不能单独推出好坏或 EV 损失。
- QA-01 仍可能补充集成/E2E 回归并改变验证数字；本文件第 3 节的 339/8 与 29 files/150 tests 只代表 2026-08-11 当前批次快照。
- **RangeBelief V2.0**：内置策略只是 8-max 100BB no-rake 2.5BB RFI（UTG→SB）的 curated 纯 raise/fold 基线，不是 solver frequency dataset；BB option、limp、open size 变体、面对 open/3-bet/4-bet、ante/rake/stack 变体仍会诚实阻断 belief 链（可用 fixture/manual policy 覆盖）。无 population/player-specific 模型；无完整 solver tree traversal，solver artifact 仅覆盖显式绑定的一个 action sequence/node；off-tree 用 nearest-size（等距取小）非插值；前端默认按选中行动者/范围侧映射 belief seat，也支持在范围面板选择 seat；前端 initialScenario 仍为 HU
- 8-max 前端：前端 initialScenario 仍为 HU；多way 场景主要经 API 使用
- docker 偶发：引擎恢复期端口绑定可能丢失（`docker port` 为空）→ `docker compose up -d --force-recreate api web`
- E2E hermetic：playwright webServer env 已清 PYTHONPATH/PYTHONHOME/DB/Redis URL/LLM key，不依赖外部服务
- live-PG 测试：conftest 防止 .env 激活；连接 5s 超时快速失败

### 本轮明确未完成（后续阶段）

- 扩展 curated preflop policy：BB option、limp、不同 open size、面对 open/3-bet/4-bet，以及 ante/rake/有效筹码变体；如需 solver 频率，必须引入带来源与许可的完整数据集，不能把当前 baseline 标作 solver-backed。
- 无 population 或 player-specific model，亦未引入 ML、Deep CFR。
- 无完整 solver tree traversal / historical inference；solver policy 只可用于显式绑定的单一 action sequence。
- 无 multiway solver policy；现有 solver 仍仅支持翻后恰好两名 active players。

## 8. 服务当前状态

compose 全栈运行中：api / web / postgres(healthy) / redis(healthy) / worker / solver-worker 全部 Up；web 200、api /health ok。
