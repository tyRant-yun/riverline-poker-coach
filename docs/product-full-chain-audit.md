# Riverline 产品全链路覆盖审计

日期：2026-08-11  
状态：首轮审计完成，P0 发布门未通过
目的：验证真实用户能否完成任务，而不是仅验证已有 fixture 或被 mock 的成功路径。

## 1. 发布判定

每条旅程同时满足以下条件才算通过：

1. **可构造**：用户能从 UI 创建所需桌型、button、seat、位置、筹码、手牌、牌面与范围；
2. **可行动**：ActionBar 能连续完成合法行动、发牌、结束与历史选择；
3. **可解释**：Range Belief、Solver、分析和教学明确说明来源、覆盖与 unavailable 原因；
4. **可复盘**：单节点与整手复盘使用真实 API，节点无未来信息，结果可回到对应行动；
5. **可追溯**：外部 Agent、本地模板、fixture、curated policy 与 Solver 的来源不能混称；
6. **可恢复**：undo/redo/load/reset/mutation 后，旧范围、Solver 与复盘不会冒充当前结果。

任一 P0 旅程无法从 UI 完成，即使后端单元测试通过，也不能宣称产品支持该能力。

## 2. 用户旅程矩阵

| 编号 | 用户任务 | 桌型/位置 | 关键行动 | 必测输出 | 等级 |
|---|---|---|---|---|---|
| J01 | 新用户从空白场景完成一手 HU | HU BTN/BB 可切换 | open/call/checkdown | Range、分析、整手复盘 | P0 |
| J02 | 为常见 HU open/call 查看范围变化 | HU | 2–3BB open、call | Prior/Current/Δ 均可用 | P0 |
| J03 | 创建并编辑 8-max 场景 | 8-max 任意 button/hero | seat/stack/position 编辑 | 牌桌与 ActionBar 一致 | P0 |
| J04 | 七个非 BB 位置做 2.5BB RFI | 8-max UTG→SB | folds + raise | curated Range Belief 可用 | P0 |
| J05 | 常见翻前分支 | HU/6-max/8-max | limp、不同 open size、call、3bet、4bet、BB option | 可用或有操作性降级 | P0 |
| J06 | 历史翻后节点求解 | HU flop/turn/river | check/bet/call/raise/fold | actionId job 隔离、grounded assessment | P0 |
| J07 | 完成牌局后复盘 | HU fold/checkdown/showdown | deal + terminal events | 所有真实决策逐点教学 | P0 |
| J08 | 6-max/8-max 多人规则与分析 | 6/8-max | fold/call/raise/all-in | replay、边池、per-seat equity | P1 |
| J09 | 修改历史与场景 | 任意 | undo/redo/load/reset/edit | stale/selection 恢复正确 | P0 |
| J10 | 外部 Agent 单节点教学 | 任意有效节点 | 生成教学解释 | provider=external、事实有界、失败降级 | P0 |
| J11 | 外部 Agent 整手复盘 | 完整/未完整牌局 | 生成整手复盘 | 逐节点 bounded facts、provider 可见 | P0 |

## 3. Range Belief 覆盖矩阵

对每个节点记录：`constructable / priorReady / provider / available / confidence / stalledAt / reason`。

### 翻前

- 桌型：2、6、8；
- 位置：BTN、SB、BB、UTG、UTG+1、MP、HJ、CO；
- 行动：fold、limp、2BB/2.2BB/2.5BB/3BB open、call、3bet、4bet、all-in、BB option；
- 来源：preflop_policy、manual、fixture（仅测试）、solver；
- 判定：默认用户路径不得依赖 fixture；unsupported 必须给出下一步操作，而不只是 `no_policy`。

### 翻后

- 街道：flop、turn、river；
- 行动：check、不同尺寸 bet、call、raise、fold、all-in；
- 链路：翻前先验 → 发牌 → 翻后行动 → Current/Δ；
- 判定：不能因为更早节点缺 policy 而在 UI 中无解释地让整条链永久不可用；若需要 Solver artifact，必须提供可完成的逐点操作路径。

### 质量与时序

- combo 质量守恒与 169 聚合一致；
- target seat 自己的 known cards 不错误阻断；
- future board 不泄漏；
- request race、mutation、load、undo/redo 后状态不会串线；
- off-tree 映射、zero probability 与 provenance mismatch 保持诚实。

## 4. Agent 接线审计

分别检查 `/v1/teaching` 与 `/v1/hand-reviews`：

- 是否实际调用同一受约束 Teacher/Agent 抽象；
- request 中是否按节点传入 bounded facts，而非整个未来牌局；
- response 是否暴露 `provider / teacherVersion / promptVersion / degraded`；
- 外部 Agent 成功、超时、非法证据引用、schema drift 时是否有测试；
- 整手 summary 是否来自 Agent，还是固定本地模板；两者必须在 UI 明确区分；
- 不允许把本地 deterministic template 显示成 Agent 分析。

## 5. 测试层级

1. **能力审计 Playwright**：真实 UI + 真实 backend；Range/Review 不做成功 mock。独立于正常绿灯 E2E，可在能力缺失时保持红色；
2. **API 覆盖矩阵**：程序化生成桌型、位置和行动线，统计真实 available 比例与失败原因；
3. **Agent 合同测试**：注入可记录调用的 fake external transport，验证单节点和整手两条路径是否真正调用；
4. **浏览器人工路径复核**：用实际页面复跑 J01/J03/J06/J07/J10/J11，检查交互与文案；
5. **发布门**：现有 pytest/vitest/build/Playwright 之外，新增 capability audit，P0 不允许 mock 掩盖。

## 6. 当前红色基线

命令：

```powershell
cd frontend
npx playwright test --config playwright.audit.config.ts
```

2026-08-11 首次结果：`0 passed / 2 failed`。

- 8-max：UI 中不存在“桌型”“按钮位”与 seat position 编辑控件；
- HU Range Belief：用户给 Hero 设置 Prior 后执行标准 open，Current 仍为 `no_policy` unavailable。

当前常规 `hand-review-workbench.spec.ts` 会拦截并返回成功的 Range、Solver 与 Hand Review 响应，因此不能代替本审计。

## 7. 输出与修复排序

最终报告按以下格式给出：

- P0/P1 缺口与最小复现；
- 后端能力、前端可达性、策略数据覆盖、Agent 接线四个维度的通过率；
- 每个 `unavailable` 的真实原因分布；
- 可在代码层修复的问题与必须补充数据/产品决策的问题分开；
- 修复批次以“先可构造，再可用，再智能化，最后扩覆盖”为顺序；
- 新发布门必须能在修复前稳定失败、修复后转绿。

## 8. 首轮审计结论

### 综合判定

**当前产品不满足 P0 全链路发布标准。** 常规回归测试仍然证明规则、状态和既有组件没有回退，但不能证明用户能完成 8-max、获得可用 Range Belief 或让整手复盘调用 Agent。

| 维度 | 实测结果 | 判定 |
|---|---:|---|
| 后端 2/6/8 人 table/button/hero 拓扑 | 104/104 可构造 | 后端能力存在 |
| Range Belief（排除 fixture） | 7/19 可用，36.8% | 覆盖不足 |
| 可用 Range 节点 | 仅 8-max 七个 2.5BB RFI | 覆盖极窄 |
| 审计样本的真实 UI→Range 端到端能力 | 0/19 | P0 失败 |
| UI 能力 Playwright | 1 passed / 2 failed | P0 失败 |
| 单节点外部 Teacher | 5 条审计通过 | 有效但 UI provenance 不完整 |
| 整手外部 Teacher | 8 个决策预期 8 次调用，实际 0 | P0 失败 |

完整证据：

- [Range/Table 覆盖报告](audits/range-table-coverage-report.md)
- [Agent/Teaching 接线报告](audits/agent-teaching-wiring-report.md)

### 已证实根因

1. **前后端能力不可达**：后端支持 2–8 人，前端只提供 HU Hero/Villain 编辑面；
2. **默认路径与策略覆盖错位**：产品默认 HU，但唯一内置真实策略是 8-max 精确 2.5BB RFI；
3. **Range 链遇到首个缺 policy 即停止**：HU open/call、limp、BB option、3/4-bet 与抽样翻后线都在早期节点 `no_policy`；
4. **整手复盘未注入 Teacher**：`/v1/hand-reviews` 直接使用本地 deterministic composer，外部 Teacher 调用数为 0；
5. **旧 E2E 证明的是编排**：关键 Range、Solver、Review 响应被成功 fixture 拦截，无法作为真实覆盖证据。

## 9. 建议修复批次

### R1：让后端能力可从 UI 构造（P0）

- 增加 table size 2–8、button seat、Hero seat、连续 seats、每 seat stack/cards/range；
- position 应根据桌型与 button 自动派生并清楚展示，不允许制造与规则矛盾的任意 position；
- import/export/load/reset/undo/redo 保留完整多座位状态；
- 让 8-max 七个 curated RFI 节点第一次真正从 UI 可达；
- 验收：8-max 红色 Playwright 转绿，并新增 6-max/8-max ActionBar 连续行动测试。

### R2：把 Range Belief 从“诚实不可用”变成“可完成工作流”（P0）

- 为默认 HU 常见 open/call/fold/3bet/4bet 定义有来源、版本和许可的 baseline policy；不得用 fixture 冒充产品策略；
- 为不同 open size 明确 exact/off-tree 产品规则与 provenance；
- 将历史节点手动 Solver 结果接入对应 actor action 的 belief provider 链，允许逐点补齐翻后 policy；
- UI 对 `no_policy` 提供操作性下一步：选择受支持 baseline、求解该行动前节点、或明确只看 Prior；
- 整手 review 的 `rangeUpdate` 必须消费真实 belief 结果，移除 deterministic v1 的固定 unavailable 占位；
- 验收：J01/J02 默认 HU 路径、J04 七个 8-max RFI 与至少一条翻后 Solver-grounded trace 转绿。

### R3：接通整手 Agent 并诚实显示来源（P0）

- 给 `build_hand_review` 注入 review-scoped Teacher；每个真实决策只传该节点 bounded facts；
- 外部成功、超时、schema drift、非法 evidence、未来牌隔离均走既有安全校验与本地降级；
- decision 与 whole-hand contract 增加 `provider / teacherVersion / promptVersion / degraded / sourceKind`；
- UI 明确区分 `external_agent` 与 `local_deterministic_template`；
- 验收：J11 的 N 决策→N 次 bounded Teacher 调用红门转绿，整手 summary provenance 可见。

### R4：重建发布门（P0）

- 保留普通快速回归；新增 capability audit 作为独立必跑门；
- P0 Range/Review/Agent 路径不得成功 mock；只有 Solver 计算本身可用持久化 deterministic artifact 替代长时求解；
- 发布报告同时给出规则通过率、UI 可达率、真实 policy 覆盖率和 Agent 调用率，不再用单一“测试全绿”代表产品完成。
