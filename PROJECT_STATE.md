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
| TeachingAgent | 外部 teaching agent 接入 compose（LLM env 插值）+ LLM 超时 60→180s（另一 worktree：fix/teaching-agent，已推送 origin） | 694faa2 |

分支：`main`（单分支工作流）+ `fix/teaching-agent`（worktree：德州扑克-worktree）。

## 3. 验证基线（2026-08-10 实测）

| 门 | 结果 |
|---|---|
| Backend pytest（仓库根，unset PYTHONPATH） | **310 passed + 8 skipped**（live-PG 需 POKER_COACH_TEST_PG_URL 才跑；RangeBelief V1.1 grounding/temporal 回归已覆盖） |
| compileall / pip check | OK |
| vitest（frontend） | **106/106**（18 文件，含 Prior/Current/Δ tabs、no-policy unavailable、deadCardsForSeat、fresh solver artifact 等回归） |
| tsc --noEmit | 0 错误 |
| next build | ✓ |
| Playwright E2E | **6/6**（compose down 后本地 hermetic webServer 实测；范围标准化流程含在内） |
| hermes verify --json | 未重跑；本轮等价实测：compileall OK、py -3.13 pip check OK、tsc/vitest/build/E2E 全部通过 |

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
- **无 grounded policy 不伪造（RangeBelief）**：no_policy / unsupported_action / zero_probability_action 显式降级；翻前自身动作无 policy 时链条诚实停止（V2 preflop 数据集前，可用 fixture/manual policy 覆盖）；`available=false` 响应只给 reason + prior，不给假 current。
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
# 完整 snapshot 链
curl -X POST http://127.0.0.1:8000/v1/ranges/trace -d '{"scenario": {...}, "seatId": 6}'
# policy 支持有序链：[{source: fixture, frequencies}, {source: solver, jobId}]
```

## 7. 已知边界

- 复盘/空手牌场景：equity 不可用是**有意**的（hero 或 villain 手牌缺失即不计算）；牌局打到结束（决策点 1 活玩家）同样合法降级——`BasicMetrics.active_player_count` 允许 1，equity 不计算（`ge=2` 仅限 equity 结果模型）
- 求解器：仅翻后（flop+）且决策点恰好 2 活玩家；bunching 忽略并记录为近似（`assumptions` 字段）
- **RangeBelief V1/V1.1**：无 grounded preflop frequency 数据集（翻前自身动作会诚实阻断 belief 链，除非用户提供 fixture/manual policy）；无 population/player-specific 模型；无完整 solver tree traversal，solver artifact 仅覆盖显式绑定的一个 action sequence/node；off-tree 用 nearest-size（等距取小）非插值；前端 belief 跟随 Hero/Villain 选择（seat 映射），暂无独立 seat 下拉
- 8-max 前端：前端 initialScenario 仍为 HU；多way 场景主要经 API 使用
- docker 偶发：引擎恢复期端口绑定可能丢失（`docker port` 为空）→ `docker compose up -d --force-recreate api web`
- E2E hermetic：playwright webServer env 已清 PYTHONPATH/PYTHONHOME/DB/Redis URL/LLM key，不依赖外部服务
- live-PG 测试：conftest 防止 .env 激活；连接 5s 超时快速失败

### 本轮明确未完成（后续阶段）

- 无 grounded preflop policy dataset；PreflopPolicy V2 / 8-max 数据集尚未开始。
- 无 population 或 player-specific model，亦未引入 ML、Deep CFR。
- 无完整 solver tree traversal / historical inference；solver policy 只可用于显式绑定的单一 action sequence。
- 无 multiway solver policy；现有 solver 仍仅支持翻后恰好两名 active players。

## 8. 服务当前状态

compose 全栈运行中：api / web / postgres(healthy) / redis(healthy) / worker / solver-worker 全部 Up；web 200、api /health ok。
