# Riverline MVP 体验手册

> 状态：发布候选；功能门已通过，正式发布仍以 release gate 和第三方许可清单闭合为准。

## 1. 当前可体验范围

首发模式固定为 **6-max、100BB、无 ante、无 rake**。用户可以：

- 与五名本地 Bot 连续对战；
- 在 Hero 决策点查看合法行动、确定性 L0 建议及其真实来源；
- 查看各非 Hero 座位基于公开事件的 Range Belief；
- 查看 VPIP、PFR、3Bet session 统计；
- 每手结束后获得自动、可恢复、不会混入未来信息的复盘；
- 刷新页面后恢复当前 session，并继续下一手。

当前 Advisor 是低延迟确定性/启发式基线，不等于高精度 Solver 或 GTO。界面会明确显示 `deterministic_formula`、heuristic provenance、置信度和 unavailable 状态。

## 2. 最快启动方式

前置条件：Windows、Python 3.13、与 `frontend/package-lock.json` 兼容的 Node.js/npm。

在 PowerShell 中运行：

```powershell
cd C:\Users\Administrator\Documents\ChatGPT\德州扑克
.\scripts\run-local.ps1
```

默认一键模式会在本次子进程中屏蔽 `.env` 的 PostgreSQL/Redis 配置，固定使用本地 SQLite 和无 Redis 降级；不会修改或泄漏你的 `.env`。仅当外部服务已经可用时运行 `./scripts/run-local.ps1 -UseExternalServices`。启动脚本会等待 API `/health` 与 Web ready，并打印 URL、模式、PID 和 `.data/local-logs/`。

然后验证：

- API health：<http://127.0.0.1:8000/health>
- Web：<http://127.0.0.1:3000>

如果一键脚本不可用，可分别启动：

```powershell
# 终端 1
cd C:\Users\Administrator\Documents\ChatGPT\德州扑克
py -3.13 -m uvicorn poker_coach.api.app:app --app-dir backend --reload

# 终端 2
cd C:\Users\Administrator\Documents\ChatGPT\德州扑克\frontend
npm install
npm run dev
```

本地体验不需要外部 LLM API Key；未配置外部能力时系统使用本地策略和诚实降级。

## 3. 推荐体验流程

1. 打开 Web 首页，切换到“持续牌桌”。
2. 选择 Bot profile，点击“开始牌桌”。
3. 核对界面只显示 Hero 私牌，其他座位不显示隐藏牌。
4. 连续完成 Fold、Call、Raise 等合法行动；观察底池、筹码、行动历史和 Bot 来源。
5. 在每个 Hero 决策点检查 Table Insights：
   - Advisor 建议及 `source`；
   - 各座位 Range Belief、置信度与 provenance；
   - VPIP、PFR、3Bet，样本不足时应显示未就绪。
6. 本手结束后检查“复盘可用/复盘未就绪”，再进入下一手。
7. 刷新浏览器，确认 session 自动重连，当前牌局或最近复盘仍可访问。

## 4. 首轮验收清单

- 连续完成至少 20 手，无非法行动、卡死或筹码异常；
- Hero 每个决策点立即出现建议或明确 unavailable，不出现旧手/旧决策建议；
- 非 Hero 私牌从不出现在 UI、公开 API 或复盘 payload；
- 下一手开始不被复盘生成阻塞；
- 刷新后 session、筹码、按钮位和手序保持一致；
- 单手输赢不被包装成决策质量结论。

## 5. 已知 MVP 边界

- Range Belief 是座位独立、公开事件驱动的低置信度启发式，不是联合 GTO range；
- L1 equity、L2 policy、轻量 Solver 和教学 Agent 尚未全部接入实时牌桌；
- 自动复盘目前保存时间正确的决策骨架，深度教学引用可能明确显示 unavailable；
- 默认使用本地 SQLite；多进程、PostgreSQL、备份与租户隔离属于 SaaS 阶段；
- 首发不承诺 8-max、ante、rake 或其他扑克变体的产品覆盖。

## 6. 反馈格式

出现问题时请记录：

- session ID、hand ID、Hero seat；
- 操作前后的 revision/手序；
- 实际行动和预期结果；
- Advisor/Range/Review 的来源或 unavailable 原因；
- 截图、浏览器控制台错误及后端终端错误。

优先反馈：规则/金额错误、私牌泄漏、恢复不一致、错误决策点建议，以及阻塞连续对战的问题。
