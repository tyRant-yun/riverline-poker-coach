# 性能基线

更新时间：2026-08-10

以下是本地开发机上的可重复基线，不是生产 SLA。牌局规则和分析核心仍以正确性优先；任何策略数据或数据库替换都需要重新测量。

## 已观察结果

| 场景 | 结果 |
|---|---:|
| 翻牌具体手牌对具体手牌的精确枚举（FastAPI TestClient） | 约 0.30 秒；约 1,081 个 runout |
| Next.js 类型检查 | 通过 |
| Next.js 生产构建 | 通过 |
| Playwright Chromium E2E（4 条） | 通过；约 8.6 秒 |
| 全量 Python 测试 | 以最后一次 `pytest` 输出为准，禁止把本表数字当固定 SLA |

## 复测命令

```powershell
cd C:\Users\Administrator\Documents\ChatGPT\德州扑克
python -m pytest --durations=10
python -m compileall -q backend/poker_coach backend/tests
cd frontend
npm run lint
npx playwright test
```

## 当前边界

- 无公共牌的具体手牌精确枚举可能达到约 1.5 百万 runout，应在 UI 中使用超时/取消或改用 Monte Carlo。
- 范围对范围精确枚举受组合数和公共牌数量共同影响；`EquityEngine` 会在超过工作量上限时拒绝。
- `/v1/analysis/jobs` 的轻量队列和取消目前是单进程边界；多进程部署必须迁移到 Redis/外部任务队列后再宣称跨进程取消。
- PostgreSQL 适配器已用伪 DB-API 连接覆盖 SQL 初始化和合同，但真实实例、连接池和迁移回滚仍需部署级测试。
