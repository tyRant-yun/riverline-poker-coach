# 工程基线

更新时间：2026-08-10

## 审计结论

初始审计时仓库是空白 Git 仓库；当时工作区唯一的原有业务外文件是用户提供的未跟踪 `AGENT.MD`。后续已建立阶段性提交；本次工作始终未修改它。

审计时未发现：

- 前端源代码、API、数据库迁移或 Docker 配置；
- README、LICENSE 或现有启动命令。

目前已建立 Python 领域核心、PokerKit 适配层、分析核心、FastAPI、SQLite 持久化、策略/学习服务和 Next.js 前端切片；当前依赖及许可证见 [`docs/dependency-inventory.md`](dependency-inventory.md)。

## 已确认的工程约束

- 规则权威源为 PokerKit，但只能通过自有适配层使用。
- API、数据库和前端不得暴露 PokerKit 类型。
- 金额使用整数最小筹码单位，不使用浮点数存储筹码。
- 确定性计算、枚举、模拟、策划策略、Solver 结果和原理教学必须标明来源等级。
- 不引入 TexasSolver 或 postflop-solver 的 AGPL 源代码。
- 首版不实现动态 Solver、视觉输入、第三方牌桌接入、真钱和多人桌。

## 当前限制

1. 当前本地默认使用 SQLite；PostgreSQL 已通过真实实例部署回归（`backend/tests/test_postgres_live.py`，PostgreSQL 16），但连接池、迁移回滚和 CI 化仍需生产化。Redis 异步任务已接入（`poker_coach.jobs`：进程内线程池兜底、Redis 队列、协作式跨进程取消；fakeredis 单测 + 真实 Redis 跨进程 E2E 验证），多 worker 部署与资源配额仍需生产化。
2. `villainHoleCards` 可以缺省以支持未摊牌场景；只有双方具体底牌都存在时才会完成摊牌比较和派奖，系统不会为未知底牌伪造赢家。
3. `rakeConfig` 已进入领域合同，但 MVP 规则适配层明确拒绝启用抽水；当前结算使用无抽水假设。
4. 分池和奇数筹码分配由 PokerKit 的 `ChipsPushing` 裁决；领域结果记录规则为底池顺序中第一位有资格获胜者取得余数，适配层不复制派奖算法。

## 已完成的可运行切片

已实现一个可在本地独立测试和运行的切片：

1. 版本化 `ScenarioSpec`、`ActionEvent`、`RangeSpec` 和分析证据模型；
2. 双方具体底牌、公共牌去重和确定性 JSON 合同；
3. PokerKit 事件重放、合法动作、错误状态和自有状态快照；
4. 弃牌直结、自动全下发牌、最佳五张比较、单赢家、分池、派奖和最终筹码；
5. 金标牌谱、非法动作和回放不变量测试；
6. 确定性数学、牌力/牌面结构、范围组合和 Equity 证据；
7. FastAPI 校验、分析、场景管理和 principle-only 教学接口；
8. SQLite 场景、版本、分析历史和复制/收藏/删除能力；
9. Next.js 人工场景编辑器、Hero/Villain 范围矩阵/组合摘要、默认范围选择、分析结果展示、保存后生成修订和指定历史版本重分析。
10. 策略场景 exact/compatible/approximate/no-match 匹配、6 组默认翻前范围，以及 A/K-high、低张连接、paired、monotone、turn barrel、river bluff catcher、thin value 和 blocker bluff 等策划教学条目；所有条目当前均不提供虚假频率。
11. Playwright Chromium E2E 覆盖规则校验、显式发翻牌、分析、教学、双方范围标准化、保存修订和历史版本重分析；教学响应支持三档解释深度，学习画像记录街道、牌面纹理表现与最近训练。

这样可以在本地不依赖 PostgreSQL、Redis 或复杂集群的情况下验证规则、分析、策略来源和学习记录边界；生产数据库和异步执行仍需后续阶段补齐。
