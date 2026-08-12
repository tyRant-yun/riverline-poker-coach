# ADR-0007：Bot/Agent 与 Advisor 使用分离且最小权限的 contract

状态：已接受
日期：2026-08-12

## 上下文

Bot 负责在时限内为自己的 seat 选择合法动作；Advisor 负责向 Hero 分层展示数学、belief、策略与不确定性。两者若共享 omniscient state 或让 Agent 直接输出规则/数值真相，会泄漏底牌、绕过 PokerKit、伪造精度，并让超时阻塞整桌。

## 决策

冻结三个独立 V1 边界：`ObservationV1` 只含观察者底牌与公共事实；`LegalActionV1` 只表达 fold/check/call/bet/raise 及明确金额语义/边界；`BotDecisionV1` 记录动作、runtime 认定的 provider/version、实测 latency、confidence/metadata 与 attempt/fallback provenance。provider 统一实现异步 `decide(observation, legal_actions, time_budget_ms, rng_seed)`。runtime 必须设置 deadline、验证返回值、再经过 PokerKit action adapter；timeout、异常或非法行动降级到本地固定/轻量策略。All-in 是 bet/raise 合法上界，不新增动作。Advisor 不实现 Bot provider，不进入 Observation，也不把 Range Belief 当已知牌。

## 备选方案

- 把完整 `ScenarioSpec`/PokerKit state 交给每个 Agent：方便但包含其他 seat 私有事实和上游类型。
- 每个 Bot 自定义 JSON：接入快，却无法统一权限、金额、版本和回退证据。
- 让 LLM/外部 Agent 直接裁决合法动作或计算关键数值：不可审计且会产生幻觉。
- 同步等待 Solver/Agent 后才推进牌局：深度更高，但违反连续对战可用性和延迟目标。

## 后果

- Provider 自报身份/latency 不可信，最终 provenance 由 runtime 重建。
- 外部进程/RPC、模型和本地策略都使用同一观察/动作 seam；适配器不得扩展隐藏字段。
- F0 只证明 in-process timeout/异常/非法行动回退；F2 仍需进程资源限制、协议握手、circuit breaker 与故障注入。
- Advisor 可异步渐进更新，但任何较深层失败都不会阻止 Hero/Bot 合法行动。
