# Riverline 重构执行复盘与后续协作规范

状态：2026-08-13 阶段复盘

适用范围：Riverline 后续 MVP、R7 决策精度升级、SaaS 化，以及类似的多 Agent 软件项目。

## 一、结论摘要

本轮重构建立了有价值的工程治理基础：独立 worktree、中央 ledger 单写、结构化 handoff、文件所有权、focused tests、风险分层审查和安全集成已经证明可行。

开发速度仍低于预期，首要原因不是 WSL 或单一模型，而是执行顺序和验收口径：

1. **工程完整性早于产品可体验性。** 后端、恢复、许可和发布门接近完成时，真实体验仍存在 `Failed to fetch`、Bot 只跟注或动作过快、不补码、固定牌局、摊牌不展示、Range/Solver 不可用、界面难读等问题。
2. **真实纵向体验门建立太晚。** 早期更多验证模块和契约，没有尽早固定“启动→连续两手→Bot/补码/随机性/摊牌→Advisor/Range/Solver→自动复盘”的黄金旅程。
3. **任务一度拆得过细。** 新进程启动、规则读取、worktree、handoff、验收和审查的固定成本接近甚至超过小改动本身。
4. **审查和测试曾被重复执行。** Worker、Reviewer、Controller 对相同范围重复读取或测试，低风险 UI 也承担了接近高风险任务的流程。
5. **状态管理一度依赖持续轮询。** 无变化时重复读取 ledger、历史和任务状态，消耗 Token 却不推进产品。
6. **跨任务 contract 缺少消费者门。** R7-01、R7-02 各自通过，集成后才发现新增 Advisor 字段 `amountSemantics` 未同步到测试 fixture。

后续默认方式应是：**用户旅程优先、纵向切片交付、最多两个实现槽、审查按风险触发、事件驱动验收、上下文最小化。**

## 二、值得保留的协作与任务管理方式

### 1. Controller、Worker、Reviewer 分工

- Controller 只负责产品顺序、依赖调度、任务 prompt、handoff 事实验收、中央 ledger 和安全集成。
- Worker 在独立分支/worktree 中实现、运行 focused tests、提交交付和 handoff。
- Reviewer 只审查高风险 diff，输出阻塞 MVP 的 P0/P1，不代替 Worker 开发。
- Product owner 处理产品取舍、范围变化和发布授权。

这套边界能避免主控陷入实现细节。后续代码审查应优先使用短生命周期子 Agent：Worker 完成后一次性提供 `base..head`、直接契约和测试证据，不持续跟踪。

### 2. 中央 ledger 单写

`docs/orchestration/ledger.md` 作为唯一活动台账是正确设计：

- Worker 不争用 ledger，只写自己的 handoff。
- Controller 区分 `completed`、`accepted`、`merged` 和 `blocked`。
- 依赖只有在真实集成后才解锁。
- 失败历史保留，例如 R6-03 无有效交付后由 R6-03B 替代，而不是覆盖事实。

### 3. 结构化 handoff

handoff 统一记录 branch、base、delivery head、changed files、测试命令、`measured`、风险和下一依赖，显著减少了主控重读实现的需求。

但 R7-01、R7-02 都曾误填 Controller thread ID，说明 thread ID、Git head、commit chain 和 changed files 应尽可能机械生成并由 linter 校验，不能只靠人工填写。

### 4. 独立 worktree 与受控并发

R7-01 负责前端布局，R7-02 负责 Advisor 后端/API，两项文件所有权不同，因此可以并行。经验是：并发不能只检查“是否改同一文件”，还必须检查是否共享 DTO、schema、事件或规则 contract。文件不冲突不代表语义不冲突。

默认同时最多两个实现槽和一个按需审查槽；规则、金额、持久化、恢复和共享 contract 链保持串行。

### 5. focused tests 与批次完整门

应保留以下测试分层：

1. Worker 运行直接 unit/contract tests。
2. 共享 DTO 变更同时运行 provider tests 与 consumer compile/type gate。
3. 每 2–3 个交付运行一次受影响模块集成门。
4. 每个体验批次运行一次黄金旅程浏览器 smoke。
5. 阶段出口或发布前只运行一次完整 backend/frontend/build/E2E/license 门。

Controller 不重复可信的 Worker 证据；Reviewer 只在需要独立反例或证据不足时复跑直接节点。

### 6. 复用原任务

小型 P1、handoff 修订、fixture 或直接集成回归应复用原 Worker。这能保留已加载上下文，避免为几行改动重复支付完整任务启动成本。只有原任务失效、范围根本变化或必须独立审查时才创建新任务。

## 三、效率阻塞、返工原因与教训

### 1. MVP 定义曾偏向工程，而不是体验

事件流、恢复、投影、PHH、许可等基础设施有长期价值，尤其对未来 SaaS 的正确性和安全很重要；问题是它们先于可体验纵向切片形成。于是“工程门通过”和“用户可以使用”脱节。

用户实际体验后才发现：

- 服务连接失败；
- Bot 动作单一或节奏不可读；
- 清台后不补码；
- 无显式 seed 时仍出现相同牌；
- contested showdown 不展示应公开手牌；
- Advisor、Range、Solver 存在不可用或不诚实状态；
- Hero、Pot、卡牌、分析区的几何和对比度不合格；
- 原产品壳和旧视觉仍影响新定位。

**教训：** MVP 的第一质量门必须是真实用户旅程，而不是“模块已经存在”的清单。

### 2. 任务过细导致固定成本过高

每个独立任务都要承担新建 worktree、读取 AGENTS/handoff/ledger、确认基线、实现、测试、两次提交、主控验收和集成。对于单字段或单 fixture 改动，这些治理成本会超过代码成本。

**教训：** 独立任务应交付一个用户可见能力，或一个能被下一能力直接消费的稳定内核。小于纵向切片的改动作为原任务修订或集成修复处理。

### 3. 审查曾超出风险收益

窄审查确实发现了有价值的 P1：outbox lease/owner、未知 schema version、PHH 私牌泄漏、终局事件缺失、旧 insights/review 覆盖新状态等。

但纯样式、文档和局部布局已有截图、几何、TypeScript 和 build 证据时，独立高强度审查收益较低。

**教训：** Reviewer 是风险控制工具，不是交付仪式。仅规则、金额、私牌、持久化、恢复、Solver/Range 核心和发布风险默认需要独立窄审查。

### 4. 重复读取、测试和轮询消耗额度

低价值消耗主要来自：

- 新进程默认完整理解仓库；
- Controller 重读 Worker 已总结的实现；
- heartbeat 重读完整 ledger/规则；
- 对无状态变化的任务持续 `wait/read`；
- Worker、Reviewer、Controller 三处重复同一测试；
- 用高强度模型处理 P2/P3、文档或单行 fixture。

**教训：** 任务管理应事件驱动。创建任务后不持续轮询，由完成通知、用户呼叫或低频 heartbeat 唤醒 Controller；无状态变化时不读仓库、不跑测试、不重复汇报。

### 5. 跨任务 contract 缺消费者验证

R7-02 修改 `frontend/types/api.ts`，但其 worktree 缺 TypeScript 依赖，前端门被标记未测；R7-01 从旧基线并行开发，因此集成后才发现 fixture 缺少 `amountSemantics`。

**教训：**

- 修改共享 DTO/schema 的任务必须指定 contract owner。
- 必须运行至少一个消费者 compile/type gate。
- 若字段要求向后兼容，应在 contract 中真正 optional，而不是名称上称 additive、类型上却必填。
- 依赖不可用必须在实现前发现，不能留到最终发布门。

### 6. WSL/shell 是次要因素

Windows sandbox、PowerShell 启动、浅对象 worktree、Node/Python 依赖和 WSL 工具差异造成过局部重试，但不是主要返工来源。主因仍是产品门、任务粒度、审查范围和共享 contract。

环境方面应坚持：

- Python/pytest 使用宿主 `py -3.13`；
- Windows worktree/Git 使用 Windows Git；
- 不在无 Python 的 WSL 重试宿主测试；
- 任务开始先确认依赖可用；
- 合并同类只读检查，减少 shell 冷启动；
- 不为一次性环境问题建立永久 workaround。

### 7. 发布与许可门应按交付物分层

源码 PR、下载二进制、容器和 SaaS 的许可/供应链要求不同。一次性把所有门绑定在本地体验版上，会延迟用户反馈。

**教训：** 每个阶段先声明发布形态，只运行与该交付物相关的许可和供应链门。

## 四、Token 与上下文管理规范

本轮没有可信的逐任务 Token 计量，因此不伪造精确消耗；但可以制定软预算：

| 用途 | 阶段预算建议 | 默认模型/强度 |
|---|---:|---|
| Controller 规划、验收、台账 | 10–15% | Luna/Terra low |
| 普通实现 | 45–55% | Terra medium |
| 高风险算法/一致性实现 | 15–25% | Sol high，且范围必须窄 |
| 独立窄审查 | 5–10% | 子 Agent；按风险选 Terra/Sol |
| 集成、发布与意外修复储备 | 10–15% | 按风险升级 |

### 高价值 Token

- 规则、金额、恢复和私牌推理；
- 公共 contract 和失败反例；
- Solver/Range 精度、采样、oracle 和性能权衡；
- 回归测试设计；
- 一次性结构化 handoff 与阶段复盘。

### 低价值 Token

- 重复读取历史或全仓；
- Controller 复述 Worker 已验证实现；
- 多个 Reviewer 重复相同测试；
- 无状态变化时持续等待；
- P2/P3 代码味道使用高强度模型；
- 单行修订创建新高强度进程。

### 最小上下文包

新任务 prompt 只需包含：

- Task ID 和单句目标；
- 精确 base commit；
- 允许/禁止修改的文件或模块；
- 直接依赖和公共 contract；
- 3–7 条验收标准；
- 必须保护的不变量；
- focused tests；
- handoff 要求。

不要传递整段父对话、所有 ADR 或完整历史。历史越多，Worker 越容易扩大范围或把旧要求当成当前目标。

### 上下文压缩后的恢复顺序

1. 完整读取 AGENTS；
2. 读取活动 ledger 行和下一入口；
3. 读取相关 handoff；
4. 核对 Git branch/head/status；
5. 使用增量 cursor 获取任务新状态。

不重新扫描全仓，不凭压缩摘要猜测提交或测试事实。

## 五、后续推荐执行模式

### 1. 固定 MVP 黄金旅程

每个体验批次必须通过：

1. 本地一键启动和健康检查；
2. 创建 6-max 牌桌；
3. Hero 连续完成至少两手；
4. Bot 展示合理 fold/call/raise 且播放节奏可读；
5. 清台座位按规则补码；
6. 无显式 seed 的两手牌不同，单手无重复牌；
7. showdown 只公开应公开的存活玩家手牌；
8. 每个 Hero 决策点同时看到 Advisor、Range 摘要和 Solver 状态；
9. 下一手不显示上一决策的旧洞察；
10. 终局自动生成可访问复盘和统计。

模块测试全绿不能替代这条旅程。

### 2. 按纵向能力拆任务

合适任务：

- Advisor 从计算、API 到 Hero dock 始终可用；
- Range V2 从公开行动更新到 169 热力图和解释；
- L1.5 从 range sampling 到多 sizing EV、置信区间和 UI provenance。

不合适任务：

- 单独任务只添加一个 DTO 字段；
- 单独任务只改一个 fixture；
- 把一条用户旅程拆成没有独立价值的 backend/frontend 小任务。

### 3. 审查决策表

| 变更类型 | 默认方式 |
|---|---|
| 文档、台账、纯样式、截图 | Worker 自验，不独立审查 |
| 普通 API/状态接线 | focused tests，复杂时才审查 |
| 规则、金额、私牌、持久化、恢复 | 子 Agent 窄审查，只报 P0/P1 |
| Solver/Range 核心 | 算法、隐私、性能窄审查，必须有 oracle/基准 |
| 发布 | 审查上一可信基线后的风险 diff，运行一次完整门 |

### 4. 集成前检查清单

- branch/base/head 正确；
- changed files 未越界；
- handoff 使用真实 task/thread ID；
- 必需 gates 是真实 `measured`；
- 工作树清洁；
- DTO/schema 有消费者验证；
- 高风险任务有独立 P0/P1 结论；
- cherry-pick 后只运行必要集成 smoke。

通过后立即更新 ledger，避免代码已合入而台账仍显示 `in_progress`。

## 六、R7 与 SaaS 阶段的应用

R7 推荐顺序：

1. 关闭 R7-02I 的单一类型 fixture 回归；
2. R7-03 只做 evaluator/oracle spike，产出采用或拒绝结论，不先改变生产路径；
3. R7-04 交付可解释、归一化、保护私牌并满足性能门的 Range V2；
4. R7-05 基于 Range V2 交付 range-aware、多 sizing、有置信区间的 L1.5；
5. R7-06 仅支持边界清晰的 HU river L2，其余场景诚实 fallback；
6. R7-07 用黄金旅程完成产品集成与真实体验验收；
7. R7-08 只运行一次发布完整门。

SaaS 化应在上述产品闭环稳定后再加入用户/会话隔离、鉴权、配额、任务队列、观测性、隐私保留策略和成本计量。不要把多租户基础设施提前混入 Range/Solver 精度研发。

## 七、立即执行的改进清单

- [ ] 独立审查使用子 Agent，且只在风险矩阵命中时创建。
- [ ] Controller 不持续跟踪；使用完成通知、用户呼叫或低频 heartbeat。
- [ ] 每个 prompt 明确 base、文件边界、contract owner 和集成门。
- [ ] DTO/schema 变更必须运行消费者 compile/type gate。
- [ ] 每个体验批次运行黄金旅程，不等发布门才验证。
- [ ] 小修订复用原 Worker，不为 fixture/handoff/单行回归创建高成本新任务。
- [ ] Worker、Reviewer、Controller 不重复同一完整测试门。
- [ ] 增加 handoff linter，自动核对 thread ID、Git 事实和 changed files。
- [ ] 记录每任务模型、耗时、工具调用和 Token 档位，形成真实成本基线。

## 八、最终原则

1. **先让用户旅程成立，再扩展基础设施。**
2. **任务交付纵向能力，不交付孤立层。**
3. **并发按语义依赖管理，不只按文件冲突管理。**
4. **审查和高强度模型只花在真实风险上。**
5. **用 handoff、Git 和增量事件恢复上下文，不用重复阅读恢复记忆。**

Riverline 的效率提升不依赖让每个 Agent 读取更多，而依赖让每个 Agent 只看到完成当前任务所必需的事实。坚持以上原则，可以在不牺牲规则正确性、私牌安全和恢复一致性的前提下，显著减少任务启动、审查、测试和上下文重建造成的返工。
