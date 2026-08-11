# Hand Review Workbench 执行台账

状态：执行中  
管理方式：事件回传、批次集成、契约验收  
上位设计：[产品与架构计划](hand-review-workbench-plan.md)  
任务定义：[任务执行表](hand-review-workbench-tasks.md)

## 1. 管理流程

每个任务按以下状态流转：

```text
ready -> active -> reported -> accepted -> integrated
                    \-> changes_requested -> active
                    \-> failed -> replanned
```

执行约定：

1. 管理任务只创建依赖已经满足的独立 Codex worktree；
2. 复杂领域、状态和 API 任务优先使用 Terra；纯展示、文档和机械任务优先使用 Luna；
3. 执行任务在自己的 worktree 中完成代码、测试和聚焦 commit；
4. 完成后通过任务最终回复回传标准报告；无需管理任务高频轮询；
5. 管理任务收到完成、失败或需协调事件后，更新本台账并处理；
6. 同一批次统一集成，再运行批次契约门；
7. 只有契约失败、接口变更、来源/provenance、时间正确性或合并冲突才触发实现级检查；
8. 批次通过后立即创建下一批已经解锁的任务。

## 2. 标准回传格式

每个执行任务的最终回复必须包含：

```text
TASK: <任务编号与名称>
STATUS: completed | changes_requested | failed
COMMITS: <按顺序列出 SHA>
FILES: <实际修改文件>
ACCEPTANCE: <逐条任务验收结果>
TESTS: <实际运行命令与结果>
RISKS: <已知边界；没有则写 none>
NEXT: <解锁的下一任务或建议>
```

不得只回复“已完成”或只给测试总数。测试失败必须保留准确输出摘要，不得用未运行的门代替。

## 3. 批次契约门

### Batch 1：决策基础与自动范围

- 玩家行动 allowlist 与后端一致；deal/blind/showdown/award 不生成可评分决策；
- 每个玩家行动都有行动前快照；
- earlier snapshot 不包含 future board；
- 选择历史行动时，节点工作区消费 `decisionSequence`，Range Belief 消费 `eventSequence`；
- 行动后自动请求正确 seat；旧请求不能覆盖新节点；
- no-policy 显示 unavailable/prior，不生成假 Current；
- backend pytest、frontend Vitest、tsc、Next build 通过。

### Batch 2：HandReview API 与节点 Solver

- N 个玩家行动返回 N 个有序 DecisionReview；
- 每个节点有独立 EvidenceBundle；
- 完成牌局、缺少手牌和无 equity 合法降级；
- Solver job 以 actionId 索引且互不覆盖；
- job provenance 与 exact decision node 匹配；
- 不支持节点不可提交并显示原因。

### Batch 3：背离与整手教学

- actual action frequency 直接来自已验证 SolverNode；
- primary/mixed/rare/absent/unscored 语义和颜色一致；
- off-tree、artifact mismatch、无具体 combo 一律 unscored；
- 每个玩家行动都有 teaching 或显式 unavailable；
- 整手 summary 只聚合逐节点已有证据；
- 外部 Teacher 失败可降级本地 Teacher。

### Batch 4：产品验收

- E2E 完成“行动 -> 范围 -> 历史节点 -> 手动 Solver -> 背离 -> 逐决策教学 -> 整手总结”；
- 现有 E2E hooks 和旧单节点流程保持兼容；
- 完整 backend/frontend/build/Playwright/Hermes 门通过；
- README、使用说明和 PROJECT_STATE 与实际能力一致。

## 4. 当前任务状态

更新时间：2026-08-11

| 任务 | 执行任务 | 状态 | 回传提交 | 集成状态 | 下一步 |
|---|---|---|---|---|---|
| PLAN | 管理任务 | integrated | `5fcd6e4` | 已进入 main | 持续维护台账 |
| DOC-入口 | Luna | integrated | `68302c6` | 已进入 main | 最终阶段再更新使用说明/状态 |
| BE-01 | Terra | integrated | `54f2b2d`, `9d25e81` | 已进入 main | BE-02 消费 DecisionSnapshot |
| FE-01 | Luna | integrated | `766c90c`, `842a24a` | 已进入 main | 等待 BE-02 响应接线 |
| FE-02/03 | Terra | integrated | `8482a2f`, `7231bf1` | 已进入 main | FE-04 复用 selected-decision 投影 |
| BE-02 | 待创建 | ready | - | - | 创建 Terra worktree |
| FE-04 | 待创建 | ready | - | - | 创建 Terra worktree |
| BE-03/04 | 未创建 | blocked_by_dependency | - | - | Batch 2 通过后创建 |
| FE-05/06 | 未创建 | blocked_by_dependency | - | - | Batch 2/3 接口稳定后创建 |
| QA/DOC | 未创建 | blocked_by_dependency | - | - | 功能集成后创建 |

## 5. 最近批次验收

Batch 1（2026-08-11）：通过。

- Backend：327 passed、8 skipped；
- Frontend：23 files、123 passed；
- TypeScript：`tsc --noEmit` 通过；
- Next.js：production build 通过；
- 主工作区仅保留用户原有 `AGENT.MD` 修改。

## 6. 当前进度判断

- Riverline 既有规则、Range Belief 与 Solver 底座：可复用；
- Hand Review Workbench 专项目标：约 40%；
- Batch 1：100%，已集成并通过统一契约门；
- 主要剩余工作：HandReview API、按节点 Solver registry、SolverAssessment、整手教学、复盘 UI 和完整 E2E。
