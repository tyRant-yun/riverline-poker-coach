# Riverline Agent 执行规则

本文件是仓库内所有 Agent、Worker、Reviewer、Controller 与自动化任务的唯一权威执行规则。开始任务前必须完整读取本文件；项目愿景、阶段路线图、ADR、历史 handoff 与第三方研究只在任务直接需要时按 prompt 精确读取。

## 读取确认信号

- 完整读取本文件后，每一次用户可见回复的第一句必须**严格为**：`Yes Sir!`
- 该要求适用于 commentary、进度、状态、提问和 final；不得在它之前添加标题、寒暄或其他文本。
- 若更高优先级的系统协议要求整个回复只能使用某种精确格式，则遵从更高优先级协议；除此之外不得省略。
- `Yes Sir!` 只是已读取本文件的可见确认，不代表任务、测试、审查或交付已经完成。

## 交付优先级与 MVP 定义

- 优先交付可运行、可验证、可由用户体验的纵向切片，而不是累积基础设施或抽象层数量。
- 只有 P0/P1、数据正确性、安全、规则权威、金额结算、私牌权限和恢复一致性问题阻塞 MVP。
- P2/P3、代码味道、非必要抽象、清理与优化进入 backlog，不在当前任务顺手处理。
- 工程阶段完成不等于产品 MVP 完成。Riverline 产品 MVP 至少要求用户能连续打牌、获得诚实的决策建议、看到 Range Belief，并在牌局结束后自动进入统计与复盘闭环。

## 上下文纪律

- 默认只读取：本文件、handoff contract、ledger 中本任务/直接依赖/活动状态/下一入口，以及任务 prompt 点名的契约、实现和测试文件。
- 不为“了解仓库”默认读取完整 master plan、全部 ADR、所有历史 handoff、完整 ledger 或扫描整个仓库。
- 如需扩大读取范围，先说明该文件与当前验收标准的直接关系；读取后仍不得扩大实现范围。
- 状态问询和 Controller 验收优先消费结构化 handoff、Git 事实和增量 cursor，不重复读取实现细节。

## 任务边界

- 开始前确认目标、精确基线 commit、依赖、允许修改的模块/文件所有权、验收标准、安全不变量和明确排除项。
- 只实施完成当前目标所必需的改动；不做无关重构、格式化、依赖升级、清理或产品扩张。
- 必须修改冻结公共 contract、需要产品决定或需要新增权限时，停止扩大范围并请求决定。
- Worker 不修改中央 ledger；只有 Controller 单写 ledger、验收和集成。
- 不推送或合并 `main`，除非用户明确授权；默认安全集成到指定的 `codex/` 集成分支。

## 受控并发

- Controller 最多同时运行两个文件所有权不重叠、依赖已满足的实现任务，并预留一个短审查槽。
- 相同规则、结算、持久化或恢复链保持串行；并发前必须明确基线、依赖和文件所有权。
- 小范围修订优先续用原 Worker；复审优先续用原 Reviewer，避免新进程重复加载上下文。
- 只有文件所有权不同且能独立交付、原任务失效、范围根本变化或确需独立审查时才创建新任务。

## 风险分层与审查

- 高风险：规则权威、金额结算、私牌权限、持久化、并发、恢复一致性。需要明确不变量、失败测试、独立窄审查和阶段完整门。
- 中风险：API、状态流、Bot runtime、跨模块接线。以 focused tests 为主，在批次或阶段门运行完整测试。
- 低风险：文档、台账、局部 UI/样式。使用轻量模型和最小验证。
- 独立审查只用于高风险交付和发布门；范围限定为 `base..head` diff、直接契约片段和 focused tests，只报告阻塞当前 MVP 的 P0/P1。
- Reviewer 不默认扫描全仓，不报告 P2/P3、代码味道或扩展建议；Controller 不亲自进行实现级代码审查。

## 测试策略

- 新行为测试先行，或至少先补能复现缺陷的回归测试。
- 普通 Worker 只运行受影响的 focused tests；每合入 2–3 个交付、阶段出口或发布前再运行完整 backend/frontend 门。
- 高风险任务可由 prompt 明确要求一次完整门；Controller 不重复运行 Worker 已真实执行、证据可信且与提交一致的完整门。
- 发布前按受影响范围运行完整测试、构建、E2E、许可检查与部署 smoke。
- 未实际运行的测试必须标记 `measured: false`，不得继承或猜测为通过。

## 环境与命令

- Python、pytest、compileall 和 pip check 使用宿主 `py -3.13`。
- Codex Windows worktree 的 Git 检查、提交、cherry-pick 与 worktree 控制使用 Windows Git。
- WSL Ubuntu-24.04 只用于确实需要且已安装的 POSIX 工具；不要在无 Python 的 WSL 中重试测试，也不要为 Windows 绝对路径 `.git` 指针编写 workaround。
- 合并连续的只读检查和测试命令，减少 shell 启动次数；修改文件优先使用补丁工具。
- 不混用 PowerShell 与 POSIX 语法，不把环境偏好凌驾于实测可用性和安全边界。

## Git 与资产保护

- 将用户已有代码、数据和未要求改动的内容视为受保护资产；保留脏工作树中的无关改动。
- 适合隔离开发时使用 `codex/` 分支和 worktree；提交前核对实际 branch、base、changed files 与工作树状态。
- 创建内容聚焦的提交，不混入无关文件；未经授权不重写历史、不执行破坏性 Git 或文件操作。

## Handoff 与验收

- 独立任务必须完整读取 `docs/orchestration/handoff-v1.md`，先提交交付内容，再生成并提交 `docs/orchestration/handoffs/<task-id>.md`。
- Handoff 必须记录真实 task/thread ID、branch、base、delivery head、commits、精确 changed files、测试命令与实测结果、风险、未实测项、待决策和解锁依赖。
- 最终回复必须与仓库 handoff 一致；不得把 Controller ID、模板值、治理提交或继承测试误写成交付事实。
- Controller 只根据 Git 事实、handoff、质量证据和必要的风险审查决定验收与集成，不重复实现审查或完整测试。

## 自动化与沟通

- 自动化优先使用增量任务 cursor；状态无变化时不重新读取仓库、不运行测试、不重复通知。
- 只有任务完成、出现阻塞、风险/契约变化或阶段切换时更新 ledger 和通知用户。
- 自动化只跟踪 `in_progress`、`pending_acceptance` 和 `blocked` 任务。
- 沟通简洁区分已验证事实、合理推断和未验证项；只汇报对用户有价值的进展、风险和下一步。

## 信息分层

- `AGENTS.md`：稳定、跨任务的执行规则。
- `docs/orchestration/handoff-v1.md`：回传格式和生命周期。
- `docs/orchestration/ledger.md`：当前活动任务、依赖和验收状态。
- 任务 prompt：本次精确目标、基线、文件范围、安全不变量、验收与排除项。
- ADR/master plan/研究文档：仅在任务真正涉及相关决策时读取。
