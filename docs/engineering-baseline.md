# 工程基线

更新时间：2026-08-09

## 审计结论

审计时仓库是空白 Git 仓库：当前分支为 `main`，尚无提交。工作区唯一的原有业务外文件是用户提供的未跟踪 `AGENT.MD`；本次工作未修改它。

审计时未发现：

- 前端源代码、API、数据库迁移或 Docker 配置；
- README、LICENSE 或现有启动命令。

目前已建立 Python 领域核心和 PokerKit 适配层；前端、API 和持久化仍未实现。当前依赖及许可证见 [`docs/dependency-inventory.md`](dependency-inventory.md)。

## 已确认的工程约束

- 规则权威源为 PokerKit，但只能通过自有适配层使用。
- API、数据库和前端不得暴露 PokerKit 类型。
- 金额使用整数最小筹码单位，不使用浮点数存储筹码。
- 确定性计算、枚举、模拟、策划策略、Solver 结果和原理教学必须标明来源等级。
- 不引入 TexasSolver 或 postflop-solver 的 AGPL 源代码。
- 首版不实现动态 Solver、视觉输入、第三方牌桌接入、真钱和多人桌。

## 当前限制

1. 还没有 FastAPI、Next.js、数据库和 Redis 启动链路。
2. PokerKit 适配层当前覆盖人工输入的盲注、常规动作、公共牌事件和全下状态；摊牌胜负需要双方具体底牌，而当前 ScenarioSpec 只保存 Hero 底牌，因此不能伪造 showdown 结果。
3. 金标牌谱还需要继续补充 split pot、具体牌型比较和非法重复动作案例。

## 已完成的首个可运行切片

已实现一个无数据库、无 Agent、可独立测试的领域核心：

1. 版本化 `ScenarioSpec`、`ActionEvent`、`RangeSpec` 和分析证据模型；
2. PokerKit 事件重放接口与领域错误模型；
3. PokerKit 适配层和自有状态快照；
4. 金额、牌面、范围、证据绑定和规则边界测试；
5. 下一步再接 FastAPI 和 Next.js。

这样可以在本地不依赖 PostgreSQL、Redis 或复杂集群的情况下验证最重要的规则不变量。
