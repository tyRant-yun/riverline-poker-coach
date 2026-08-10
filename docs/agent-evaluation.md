# 教学 Agent 评测基线

本地教学实现是确定性的 `TeachingService`；`ExternalModelTeacher` 通过同一只读证据边界调用外部模型。两者都输出现有 `TeachingResponse` 合同。评测固定关注事实一致性，而不是文风。

代码边界由 `TeachingToolGateway` 固定：场景、合法动作、EvidenceBundle、范围、策略匹配和术语只能通过读取工具取得；`create_practice` 会重新经过 `LearningService` 验证，工具没有改写牌局事实的方法。

## 固定断言（本地与外部模型通用）

- 带数字的 `TeachingText` 必须有 `evidenceReferences`。
- 推荐行动必须引用证据；没有获批准的定量策略条目时，`frequency` 和 `ev` 必须为空。
- 教学响应引用的 `evidenceId` 必须存在于当前 `EvidenceBundle`。
- 教学层不生成未验证的练习题；练习必须由 `LearningService` 重新分析并保存预期证据。
- 同一 `ScenarioSpec` 的本地教学输出必须可复现。
- `beginner`、`intermediate`、`advanced` 深度必须写入 `TeachingResponse`；高级范围解释中的数字仍必须引用 EvidenceBundle。

## 外部模型适配器的附加边界（`backend/tests/test_external_teacher.py`）

- 非法行动拒绝：推荐动作不在合法动作集合时被丢弃，不进入响应。
- 证据引用过滤：模型引用的未知 `evidenceId` 被删除；净化后仍无引用的数字文本被确定性占位文本替换（不向用户输出无引用数字）。
- 用户自由文本只出现在 user 角色消息中，绝不进入事实区块或系统提示（防 Prompt Injection 边界）。
- 失败降级：传输、解析或校验失败时自动降级到本地 `TeachingService`（principle-only），API 信封返回 `provider: external_llm` 与 `degraded: true`。
- 策略频率门控：没有 `can_quote_frequencies` 批准时，传入模型的策略事实中 `frequency`/`ev` 恒为空。

## 运行

```powershell
cd C:\Users\Administrator\Documents\ChatGPT\德州扑克
python -m pytest backend/tests/test_agent_groundedness.py backend/tests/test_strategy_catalog.py backend/tests/test_external_teacher.py
```

外部模型接入通过环境变量启用：`POKER_COACH_LLM_API_KEY`（必需）、`POKER_COACH_LLM_BASE_URL`（默认 OpenAI 兼容端点）、`POKER_COACH_LLM_MODEL`、`POKER_COACH_LLM_TIMEOUT_SECONDS`；未设置密钥时始终使用本地教师。
