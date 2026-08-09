# 德州扑克策略教学产品

当前状态：阶段 0 已完成，阶段 1 领域合同和阶段 2 PokerKit 适配层首个切片已实现。

## 本地验证

当前首个可运行切片是 Python 领域核心，暂不需要 PostgreSQL、Redis 或前端依赖：

```powershell
cd backend
python -m pytest
```

预期结果：12 个领域与规则适配测试通过。

## 工程文档

- [工程基线](docs/engineering-baseline.md)
- [MVP 架构决策](docs/adr/0001-mvp-architecture-decisions.md)
- [依赖与许可证清单](docs/dependency-inventory.md)
- [开发规范](AGENT.MD)

## 当前边界

已经实现的是 PokerKit 无关的版本化领域合同，不是完整牌局规则引擎。下一步应实现 PokerKit 适配层、事件重放、合法动作服务和金标牌谱测试；在此之前不接入 FastAPI、数据库或教学 Agent。
