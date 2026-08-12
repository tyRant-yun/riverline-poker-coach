# Riverline 产品能力修复执行计划

日期：2026-08-11
依据：`product-full-chain-audit.md`、Range/Table 与 Agent/Teaching 两份审计报告

## 1. 目标与口径

本轮目标不是恢复“测试全绿”的表述，而是让真实用户完成以下 P0 任务：

1. 从 UI 创建 HU、6-max、8-max 场景并选择 button/Hero；
2. 在默认 HU 常见行动线中获得有来源的 Prior/Current/Δ；
3. 在 8-max 七个受支持 RFI 位置使用现有 curated policy；
4. 让整手 review 消费真实 Range Belief，而非固定 unavailable 占位；
5. 让整手教学真正调用配置的外部 Teacher，并在 UI 显示来源和降级；
6. 用不成功 mock 关键能力的审计门证明上述路径。

完成度必须分别报告：UI 可达率、policy 覆盖率、Agent 调用率与普通回归结果。任何一个维度失败都不能称为 100%。

## 2. 不可违反的设计边界

- 后端规则重放仍是 table/seat/position/actor 的唯一权威；
- position 由 table size、button 与 seat 自动派生，UI 不允许任意制造矛盾位置；
- 新 policy 必须有版本、来源、适用节点和 confidence；不得把 fixture、heuristic 或 curated baseline 称作 Solver/GTO；
- Range Belief 仍在 combo 层更新，169 只是视图；
- Solver artifact 必须通过持久化 jobId 与 exact-node provenance；
- Agent 每次只接收单个行动前节点的 bounded facts，禁止未来牌泄漏；
- local template 与 external Agent 必须通过 `sourceKind/provider/version/degraded` 明确区分；
- 原有 actionId、undo/redo、amountType、E2E hooks 和完成牌局语义不能回退。

## 3. 批次与任务

### Batch A：可构造 + 默认 Range 可用

#### RM-01 多座位 ScenarioEditor（Terra，复杂）

范围：frontend 场景编辑、seat/range 编辑与状态迁移。

- table size 2–8；
- button seat 与 Hero seat；
- 连续 seat 列表、派生 position、每 seat stack；
- known cards/rangesBySeat 的 seat 驱动编辑；
- HU 保留简洁 Hero/Villain 模式，多座位使用 seat 面板；
- table size/button 变化时重新派生 seats/positions，并诚实失效 action history、belief、solver、review；
- import/export/load/reset/undo/redo 保留多座位状态；
- 8-max curated RFI 能从 UI 构造并行动。

验收：

- capability audit 的 8-max 构造红门转绿；
- 新增 6-max/8-max button/Hero/seat/stack/range 测试；
- ActionBar actor 与后端重放一致；
- 不允许手工输入与 button 矛盾的 position。

#### RM-02 HU curated preflop policy（Terra，复杂）

范围：backend versioned policy artifact/provider，以及最小 frontend provider 选择接线。

- 先审计并复用现有 first-party BTN open、BB defend/3bet、BTN vs 3bet/4bet、BB vs 4bet 资产；
- 覆盖默认 HU 100BB、no ante/no rake 的常见 open size 与后续 call/fold/3bet/4bet 节点；
- 输出完整 action-frequency table，而不是只返回 observed-action membership；
- 明确 `source=preflop_policy`、`confidence=curated`、版本与适用边界；
- 不足以支撑频率的资产必须在报告中指出，不能编造；
- frontend 对受支持 HU/8-max 节点自动请求该 provider；
- limp、BB option 或未覆盖尺寸继续 no_policy，但 UI/metadata 要能给出具体原因。

验收：

- 默认 HU open 的 Current Range 红门转绿；
- open/call/fold/3bet/4bet 的 provider 边界测试；
- 原 8-max 7/7 RFI 不回退；
- fixture 继续只用于测试，不计产品覆盖。

Batch A 集成门：backend coverage harness、capability Playwright、pytest、vitest、tsc、build。

### Batch B：整手真实 Range + Agent

#### RM-03 HandReview RangeUpdate

- 对每个真实行动调用相同的 Range Belief/trace 服务；
- 使用行动后 eventSequence 和节点可用 provider/job；
- 返回真实 prior/current/delta/source/confidence/reason；
- 删除 `deterministic-hand-review v1` 固定 unavailable 占位；
- policy 缺口仍诚实降级，并绑定对应 actionId。

#### RM-04 HandReview Teacher

- 给 review service 注入 configured Teacher；
- N 个真实决策产生 N 次 bounded Teacher 调用；
- whole-hand summary 只聚合已净化的逐节点输出，必要时使用独立 bounded summary call；
- 增加 `provider/teacherVersion/promptVersion/degraded/sourceKind`；
- 外部成功、超时、schema drift、非法 evidence 与未来牌隔离测试；
- local deterministic fallback 始终明确标识。

RM-03 与 RM-04 都会修改 review contract/service，按顺序执行，不并行提交。

### Batch C：前端操作性与 provenance

#### RM-05 Review/Range/Agent UI

- Range unavailable 显示可操作下一步：使用支持的 baseline、求解行动前节点、或仅查看 Prior；
- DecisionReview 与整手 summary 显示 Range/Agent 的来源、版本、confidence、degraded；
- selected action 的 Solver artifact 可回填对应 Range provider；
- 保留单节点 TeachingPanel，并补显示 promptVersion；
- 不把 local template、curated policy 或 off-tree 映射称为 Agent/Solver 结论。

### Batch D：真实发布门

#### RM-06 QA 与文档

- capability audit 的 P0 用例必须转绿；
- 普通 E2E 保留，但关键 Range/Review/Agent 路径不允许成功 mock；
- 增加 live grounded Solver artifact 的至少一条翻后 Range trace；
- 增加 6/8-max 多人 all-in/边池/equity UI 路径；
- 更新 PROJECT_STATE、使用说明与覆盖数字；
- 发布报告同时列出 unsupported 节点，不用单一百分比掩盖边界。

## 4. 执行顺序

```text
Batch A: RM-01 ─┐
                ├─ 集成门 ─> RM-03 ─> RM-04 ─> RM-05 ─> RM-06
         RM-02 ─┘
```

RM-01 与 RM-02 文件边界基本独立，可并行。后续任务按 contract 依赖串行，避免 review models/service 和 page state 同时冲突。

## 5. 当前状态

| 任务 | 状态 | 执行任务 | 提交 | 备注 |
|---|---|---|---|---|
| RM-01 | integrated | Terra `019ff0ed-7d88-7e52-8d13-bd19188c3914` | `a2e9e6f` → `eb1ba3c` | 2–8 seat、button/Hero、派生位置与 UI 构造门已转绿 |
| RM-02 | integrated | Terra `019ff0ed-7d8d-7673-bd99-be5633258225` | `c539b49` → `e0aa99e` | HU 常见 2BB open 分支与原 8-max RFI policy 均可用 |
| RM-03 | integrated | Terra `019ff116-d0ca-75f0-9927-41f18e3793f7` | `db74f24` → `e71ec37` | 每个真实行动返回同源 Range Trace 更新；主线完整后端门通过 |
| RM-04 | integrated | Terra `019ff121-427d-75d0-b1e9-d1f49b9c35c7` | `f65d276` → `c7ea622` | configured Teacher 已逐决策接入；J10/J11 转绿 |
| RM-05 | waiting_user_instruction | - | - | 未派发；本轮执行在 RM-04 收口后暂停 |
| RM-06 | waiting_user_instruction | - | - | 未派发；等待下一轮指令 |

### Batch A 集成门结果

- backend：`348 passed, 8 skipped`，`compileall` 通过；
- Range coverage harness：非 fixture `11/20` 可用；默认 HU 2BB open、BB fold/call/3bet、BTN fold/call/4bet 与 8-max 七个 RFI 节点有 curated provenance，未覆盖节点继续 `no_policy`；
- frontend：Vitest `30 files / 157 tests`，`tsc --noEmit` 与 Next build 通过；
- 普通 Playwright：隔离服务 `8/8` 通过；
- capability Playwright：隔离服务 `3/3` 通过，HU 连续性、8-max UI 构造、HU Current Range 三个真实门全部转绿。

验收使用当前主线 HEAD 的临时 detached worktree 与 13000/18000 一次性服务，强制 local Teacher，未复用 3000/8000 的长期联调服务。后者已确认启用 external Teacher，教学请求可超过 Playwright 的 15 秒客户端等待但最终返回 200；该现象属于联调服务时延，不计为 Batch A 产品回归。

### RM-03 集成门结果

- `POST /v1/hand-reviews` 的真实玩家行动均返回 actionId/seatId/afterSequence 对齐的 combo 级 prior/current/delta；
- RangeUpdate 复用共享 Range Trace，支持 curated HU/8-max policy 与 exact-node Solver artifact，未覆盖或错节点 artifact 诚实降级；
- 行动前教学与行动后范围更新保持时序分离，早期节点无未来牌泄漏；
- 主线 `backend/tests` 完整通过（保留 8 个既有 skip），`compileall` 与 `git diff --check` 通过。

### RM-04 集成门结果

- `/v1/hand-reviews` 使用 configured Teacher，每个真实决策按 actionId 顺序执行一次 bounded 调用，deal/state 事件排除；
- external 输出沿用既有 schema/evidence 校验，单节点 timeout、transport、schema drift 或非法 evidence 会诚实降级，不污染其他节点；
- per-decision 与整手聚合均返回可区分的 provider/version/promptVersion/sourceKind/degraded provenance，整手总结明确为 `aggregated_local`；
- Agent/Teaching J10/J11 audit `11/11` 通过，完整后端测试 `370 passed, 8 skipped`，`compileall` 与 `git diff --check` 通过。

按用户指令，本轮执行在 RM-04 集成完成后停止；未创建 RM-05/RM-06 任务，等待下一轮指令。

## 6. 回传与集成规则

- 独立任务必须使用 worktree；
- 复杂任务用 Terra，最终简单文档收口可用 Luna；
- 每个任务完成前显式跨任务回传 TASK/STATUS/COMMITS/FILES/ACCEPTANCE/TESTS/RISKS/NEXT；
- 管理任务只做范围检查、批次 cherry-pick 与统一合同门，不逐文件重复审查；
- intentional red audit 只有在对应能力实现后才能转绿，不能删除或改成 mock。
