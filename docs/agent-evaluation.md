# 教学 Agent 评测基线

当前本地教学实现是确定性的 `TeachingService`，它模拟未来结构化 Agent 的只读证据边界。评测固定关注事实一致性，而不是文风。

代码边界由 `TeachingToolGateway` 固定：场景、合法动作、EvidenceBundle、范围、策略匹配和术语只能通过读取工具取得；`create_practice` 会重新经过 `LearningService` 验证，工具没有改写牌局事实的方法。

## 固定断言

- 带数字的 `TeachingText` 必须有 `evidenceReferences`。
- 推荐行动必须引用证据；没有获批准的定量策略条目时，`frequency` 和 `ev` 必须为空。
- 教学响应引用的 `evidenceId` 必须存在于当前 `EvidenceBundle`。
- 本地教学层不生成未验证的练习题；练习必须由 `LearningService` 重新分析并保存预期证据。
- 同一 `ScenarioSpec` 的本地教学输出必须可复现。
- `beginner`、`intermediate`、`advanced` 深度必须写入 `TeachingResponse`；高级范围解释中的数字仍必须引用 EvidenceBundle。

## 运行

```powershell
cd C:\Users\Administrator\Documents\ChatGPT\德州扑克
python -m pytest backend/tests/test_agent_groundedness.py backend/tests/test_strategy_catalog.py
```

外部模型 Agent 接入后，必须复用这些断言，并增加：非法行动拒绝、用户自由文本不可升级为系统指令、缺失数据时明确降级、中文术语稳定性和跨语言事实一致性。
