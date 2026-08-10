# 性能基线

更新时间：2026-08-10

以下是本地开发机上的可重复基线，不是生产 SLA。牌局规则和分析核心仍以正确性优先；任何策略数据或数据库替换都需要重新测量。

## 已观察结果

| 场景 | 结果 |
|---|---:|
| 翻牌具体手牌对具体手牌的精确枚举（FastAPI TestClient） | 约 0.30 秒；约 1,081 个 runout |
| Monte Carlo 具体手牌对具体手牌，200k trials（翻前，无公共牌） | 约 3.3 秒（约 60k trials/s） |
| Monte Carlo 具体手牌对具体手牌，200k trials（翻牌，3 张公共牌） | 约 0.4 秒（约 500k trials/s，评估器缓存命中） |
| Monte Carlo 1M trials 推算（翻前 / 翻牌） | 约 17 秒 / 约 2 秒，低于 API 默认 120 秒超时 |
| Next.js 类型检查 | 通过 |
| Next.js 生产构建 | 通过 |
| Playwright Chromium E2E（4 条） | 通过；约 8.6 秒 |
| 全量 Python 测试 | 以最后一次 `pytest` 输出为准，禁止把本表数字当固定 SLA |

2026-08-10 优化：7 张牌评估改为直接评估器 + LRU 缓存（替代 21 个五张子集取最大），非加权 Monte Carlo 热路径不再做 Decimal 累加；差分测试（随机 5-7 张牌 1,200 组 vs 暴力参考实现）保证等价。

## 复测命令

```powershell
cd C:\Users\Administrator\Documents\ChatGPT\德州扑克
py -3.13 -m pytest --durations=10
py -3.13 -m compileall -q backend/poker_coach backend/tests
cd frontend
npm run lint
npx playwright test
```

## 当前边界

- 无公共牌的具体手牌精确枚举可能达到约 1.5 百万 runout，应在 UI 中使用超时/取消或改用 Monte Carlo。
- 范围对范围精确枚举受组合数和公共牌数量共同影响；`EquityEngine` 会在超过工作量上限时拒绝。
- `/v1/analysis/jobs` 支持进程内线程池与 Redis 队列两种后端；Redis 后端已通过真实跨进程 E2E（独立 worker 执行与运行中取消）。
- PostgreSQL 适配器已通过真实实例部署回归（`backend/tests/test_postgres_live.py`）；连接池（psycopg_pool）与迁移回滚仍需部署级测试。
