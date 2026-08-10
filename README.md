# 德州扑克策略教学产品

当前状态：已完成一个可本地运行的 HU NLHE MVP 核心切片。当前覆盖事件重放、合法动作、牌力与牌面分析、精确/模拟 Equity、证据汇总、策略目录匹配、FastAPI、SQLite 场景/修订/分析历史、验证练习和 Next.js 场景编辑器；教学层支持证据约束、三档解释深度和合法动作边界。自适应训练、真实外部模型 Agent、Redis 多进程任务和动态 Solver 仍在后续迭代。

## 本地验证

后端测试、编译和依赖检查：

```powershell
cd C:\Users\Administrator\Documents\ChatGPT\德州扑克
python -m pytest
python -m compileall -q backend/poker_coach backend/tests
python -m pip check
```

测试入口从仓库根目录执行，覆盖领域合同、PokerKit 适配层、金标牌谱、回放不变量、分析核心、专用 Equity API、场景修订重分析、持久化和教学证据绑定。

## 本地启动

启动后端：

```powershell
cd C:\Users\Administrator\Documents\ChatGPT\德州扑克
python -m uvicorn poker_coach.api.app:app --app-dir backend --reload
```

启动前端（另开终端）：

```powershell
cd C:\Users\Administrator\Documents\ChatGPT\德州扑克\frontend
npm install
npm run dev
```

前端默认访问 `http://127.0.0.1:3000`，并调用 `http://127.0.0.1:8000` 的 API；可用 `NEXT_PUBLIC_API_BASE_URL` 覆盖。默认 SQLite 文件位于 `.data/`，不会提交到 Git。

生产或集成环境可设置 `POKER_COACH_DATABASE_URL` 切换到 PostgreSQL；需先安装可选依赖 `pip install -e ".[postgres]"`。未设置时始终使用 SQLite。

API 默认限制单请求体为 1 MiB、单次分析超时为 120 秒、匿名会话每分钟 120 个请求；可用 `POKER_COACH_MAX_REQUEST_BYTES`、`POKER_COACH_MAX_TIMEOUT_SECONDS` 和 `POKER_COACH_RATE_LIMIT_PER_MINUTE` 调整，限流设为 `0` 可关闭（仅适合本地测试）。

也可以使用 PowerShell 一键启动本地后端和前端：

```powershell
.\scripts\run-local.ps1
```

## 工程文档

- [工程基线](docs/engineering-baseline.md)
- [MVP 架构决策](docs/adr/0001-mvp-architecture-decisions.md)
- [策略匹配边界](docs/adr/0003-strategy-match-frequency-boundary.md)
- [依赖与许可证清单](docs/dependency-inventory.md)
- [开发规范](AGENT.MD)

## 当前边界

PostgreSQL 适配已提供可选的 psycopg3 存储边界，但尚未在本地仓库之外的真实 PostgreSQL 实例上做部署回归；Redis/异步任务、完整外部模型 Agent 和真正的跨进程取消仍待后续阶段。前端 E2E 已覆盖保存、修订、历史重分析和导入流程。当前教学服务只使用 EvidenceBundle 提供 principle-only 解释；没有可靠策略数据时不会输出虚假 GTO 频率。

示例场景见 [examples/scenario-flop.json](examples/scenario-flop.json)，安全和运维边界见 [安全、隐私与运维](docs/security-privacy-operations.md)。编辑器支持 ScenarioSpec JSON 导入/导出；教学层的只读工具边界和评测见 [教学 Agent 评测基线](docs/agent-evaluation.md)。
