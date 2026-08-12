# Codex task handoff contract v1

状态：已采用

## 目的与角色

独立 Codex 开发任务通过仓库内 handoff 文件主动回传可验证事实，主控任务据此验收、合并并更新中央执行台账。

- **Worker**：只负责自己的任务分支、提交和 `docs/orchestration/handoffs/<task-id>.md`。
- **Controller**：读取 handoff、复核 Git/质量证据、决定是否验收或合并，并且是 `docs/orchestration/ledger.md` 中央状态行的唯一写入者。
- **Product owner**：处理 handoff 中确实需要产品决定的 `decisions_needed`。

## 生命周期

1. Worker 开始前阅读本 contract、ledger 中的依赖状态和任务专属规范。
2. Worker 在独立分支完成范围内工作并提交交付内容。
3. Worker 以已提交的交付内容为事实生成 handoff，运行 handoff/差异检查，并把 handoff 文件提交到任务分支。
4. Worker 的最终消息结构化回传同一组事实；不得用最终消息补写或覆盖 handoff 中的不同结论。
5. Controller 验证 branch、commits、changed files、quality gates 和风险；验收/合并后由 Controller 更新 ledger。

`head_commit` 是**任务交付内容的最高提交**，不包含随后写入 handoff 文件的治理提交。这避免 handoff 文件必须预知包含自身的 commit SHA。Controller 仍须从 Git 独立读取实际 branch tip。`commits` 同样只列任务交付提交，不列纯 handoff 治理提交。

## 文件与状态

- 路径：`docs/orchestration/handoffs/<task-id>.md`。
- `<task-id>` 必须与文件内 `task_id` 完全一致，建议只使用字母、数字、点、下划线和连字符。
- `status` 只允许：
  - `completed`：约定范围已完成且必需质量门已有真实结果；
  - `blocked`：仍有阻止完成的外部条件或产品决定，必须在 `risks`/`decisions_needed` 写明。
- 不用 `completed` 表示“代码写完但未验证”，也不用继承基线冒充本任务实测。

## 必需字段

| 字段 | 约束 |
|---|---|
| `task_id` | 稳定任务标识，与 handoff 文件名一致 |
| `thread_id` | 执行本任务的 Codex thread ID；不得写成固定模板值 |
| `branch` | Worker 实际任务分支 |
| `base_commit` | 开始任务时的基线 Git object ID；优先完整 SHA，至少为仓库内唯一短 SHA |
| `head_commit` | handoff 治理提交之前，任务交付内容的最高 commit |
| `status` | `completed` 或 `blocked` |
| `scope` | 本任务目标、包含项及明确排除项 |
| `changed_files` | 相对仓库根的精确文件列表；生成物也必须列出 |
| `commits` | 交付 commit 的 SHA 与 subject，按时间顺序 |
| `quality_gates` | 每项包含原始命令、结果与 `measured`；未跑必须为 `false` 并说明原因 |
| `artifacts` | 可供主控/后续任务消费的文档、fixture、报告或构建产物 |
| `risks` | 已知限制、证据缺口和回退注意事项；无风险用空列表 |
| `decisions_needed` | 需要产品负责人/主控决定的问题；无则为空列表 |
| `dependencies_unlocked` | 本任务完成后可启动的任务 ID/能力；阻塞状态通常为空 |
| `recommended_next` | 建议下一任务、目标和依赖，不代表已授权启动 |

## 推荐模板

Handoff 文件使用 Markdown；机器可核对的事实放在一个 YAML code block 中：

```yaml
contract_version: handoff/v1
task_id: TASK-01
thread_id: <actual-thread-id>
branch: codex/task-01
base_commit: <git-object-id>
head_commit: <delivery-head-commit>
status: completed
scope:
  goal: <one sentence>
  included:
    - <delivered scope>
  excluded:
    - <explicit non-goal>
changed_files:
  - path/to/file
commits:
  - sha: <full-sha>
    subject: <commit subject>
quality_gates:
  - command: <exact command>
    result: <exit/result summary>
    measured: true
artifacts:
  - path: path/to/artifact
    description: <consumer-facing meaning>
risks: []
decisions_needed: []
dependencies_unlocked:
  - NEXT-01
recommended_next:
  - task_id: NEXT-01
    goal: <next bounded goal>
    depends_on:
      - TASK-01
```

可在 YAML 后补充简短说明，但不能改变 YAML 的事实语义。

## 一致性与验证规则

- 最终消息必须包含或等价呈现上述必需字段，并与仓库 handoff 文件逐项一致。
- `branch`、`base_commit`、`head_commit` 和 `commits` 必须从 Git 读取，不凭记忆填写。
- `changed_files` 必须由交付 commit diff 产生，不用人工挑选成“主要文件”。
- 每个 quality gate 都要保留原始命令；`measured: true` 只表示本任务分支实际执行并得到结果。
- 继承的主线/集成基线可以写入 `result` 作为上下文，但必须 `measured: false`，不得写成通过。
- 阻塞任务不得隐藏未提交改动、跳过门或决策缺口；能提交的诊断/文档仍应提交并记录真实 head。
- Worker 不修改 ledger 中央状态行。并行 Worker 只新增自己的 handoff 文件，避免共同编辑热点。
