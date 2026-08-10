# 德州扑克策略教学产品

当前状态：已完成一个可本地运行的 HU NLHE MVP 核心切片。当前覆盖事件重放、合法动作、牌力与牌面分析、精确/模拟 Equity、证据汇总、策略目录匹配、FastAPI、SQLite 场景/修订/分析历史、验证练习和 Next.js 场景编辑器；教学层支持证据约束、三档解释深度和合法动作边界。自适应训练、真实外部模型 Agent、Redis 多进程任务和动态 Solver 仍在后续迭代。

## 本地验证

后端测试、编译和依赖检查：

```powershell
cd C:\Users\Administrator\Documents\ChatGPT\德州扑克
py -3.13 -m pytest
py -3.13 -m compileall -q backend/poker_coach backend/tests
py -3.13 -m pip check
```

测试入口从仓库根目录执行，覆盖领域合同、PokerKit 适配层、金标牌谱、回放不变量、分析核心、专用 Equity API、场景修订重分析、持久化和教学证据绑定。

## 本地启动

启动后端（项目依赖安装在 Python 3.13，用 `py -3.13` 调用）：

```powershell
cd C:\Users\Administrator\Documents\ChatGPT\德州扑克
py -3.13 -m uvicorn poker_coach.api.app:app --app-dir backend --reload
```

**环境变量配置**：仓库根目录提供 `.env.example`（含全部可配置项与注释）。复制为 `.env` 并按需填写即可，应用启动时自动加载（已设置的环境变量优先）：

```powershell
Copy-Item .env.example .env
# 编辑 .env，填入 DeepSeek Key 即可唤醒外部教学 Agent：
#   POKER_COACH_LLM_BASE_URL=https://api.deepseek.com/v1
#   POKER_COACH_LLM_API_KEY=sk-...
#   POKER_COACH_LLM_MODEL=deepseek-chat
```

`.env` 已被 `.gitignore` 排除，不会提交；`.env.example` 会随仓库维护。

启动前端（另开终端）：

```powershell
cd C:\Users\Administrator\Documents\ChatGPT\德州扑克\frontend
npm install
npm run dev
```

前端默认访问 `http://127.0.0.1:3000`，并调用 `http://127.0.0.1:8000` 的 API；可用 `NEXT_PUBLIC_API_BASE_URL` 覆盖。默认 SQLite 文件位于 `.data/`，不会提交到 Git。

生产或集成环境可设置 `POKER_COACH_DATABASE_URL` 切换到 PostgreSQL；需先安装可选依赖 `pip install -e ".[postgres]"`。未设置时始终使用 SQLite。本地部署回归可用 `.\scripts\dev-services.ps1` 一键启动 PostgreSQL 16 和 Redis 7 容器（Docker Desktop），然后运行 `backend/tests/test_postgres_live.py`（需设置 `POKER_COACH_TEST_PG_URL`，未设置时自动跳过）。

分析任务默认在本进程内由线程池执行。设置 `POKER_COACH_REDIS_URL`（并安装可选依赖 `pip install -e ".[redis]"`）后切换为 Redis 队列：默认在同一进程内启动一个消费线程（本地便捷模式），部署独立 worker 时设置 `POKER_COACH_REDIS_WORKER_IN_PROCESS=0` 并另起 `py -3.13 -m poker_coach.jobs --redis-url <url>`。取消通过 Redis 标志协作生效，可跨进程终止运行中的 Equity 计算。

教学默认使用本地确定性教师。设置 `POKER_COACH_LLM_API_KEY` 后切换为外部模型教师（OpenAI 兼容 chat-completions 端点）：可用 `POKER_COACH_LLM_BASE_URL`、`POKER_COACH_LLM_MODEL`、`POKER_COACH_LLM_TIMEOUT_SECONDS` 调整。外部教师只注入 Gateway 事实，非法行动与未引用证据的数字会被过滤，调用失败自动降级回本地教师（API 响应含 `provider` 与 `degraded` 字段）。

API 默认限制单请求体为 1 MiB、单次分析超时为 120 秒、匿名会话每分钟 120 个请求；可用 `POKER_COACH_MAX_REQUEST_BYTES`、`POKER_COACH_MAX_TIMEOUT_SECONDS` 和 `POKER_COACH_RATE_LIMIT_PER_MINUTE` 调整，限流设为 `0` 可关闭（仅适合本地测试）。

也可以使用 PowerShell 一键启动本地后端和前端：

```powershell
.\scripts\run-local.ps1
```

## Docker 部署（API + 独立 worker + PostgreSQL + Redis）

```powershell
docker compose up -d            # 构建并启动 4 个容器
curl http://127.0.0.1:8000/health
```

- `api` 容器使用 PostgreSQL 与 Redis；`POKER_COACH_REDIS_WORKER_IN_PROCESS=0`，分析作业由独立的 `worker` 容器消费，取消可跨容器生效。
- 首次部署可执行 `docker compose exec api alembic upgrade head` 走迁移路径（存储层自举与迁移幂等，两者可共存）。
- 停止：`docker compose down`；数据卷 `pgdata` 保留，`docker compose down -v` 可连数据一并删除。

## 工程文档

- [工程基线](docs/engineering-baseline.md)
- [MVP 架构决策](docs/adr/0001-mvp-architecture-decisions.md)
- [策略匹配边界](docs/adr/0003-strategy-match-frequency-boundary.md)
- [Solver 技术评估](docs/adr/0004-solver-evaluation.md)
- [Solver 输出导入规范](docs/solver-import-spec.md)
- [Solver Integration Design Review](docs/solver-integration-design.md)
- [BYO DeepSeek Key 端到端加密设计](docs/design-bring-your-own-key.md)
- [依赖与许可证清单](docs/dependency-inventory.md)
- [开发规范](AGENT.MD)

## 当前边界

PostgreSQL 适配已通过真实实例部署回归（PostgreSQL 16，见 `backend/tests/test_postgres_live.py`：schema 迁移、场景/修订/分析/学习记录与 SQLite 对拍、完整 HTTP 流程）；连接池和迁移回滚仍待生产化。Redis 异步任务已实现（`poker_coach.jobs`：进程内线程池兜底 + Redis 队列 + 协作式跨进程取消，fakeredis 单测 + 真实 Redis 跨进程 E2E 验证）。外部模型 Agent 适配器已实现（`coach/external.py`：只读 Gateway 事实注入、非法行动过滤、证据引用净化、失败降级到本地 principle-only 教师），通过 `POKER_COACH_LLM_API_KEY` 等环境变量启用。前端 E2E 已覆盖保存、修订、历史重分析和导入流程。

示例场景见 [examples/scenario-flop.json](examples/scenario-flop.json)，安全和运维边界见 [安全、隐私与运维](docs/security-privacy-operations.md)。编辑器支持 ScenarioSpec JSON 导入/导出；教学层的只读工具边界和评测见 [教学 Agent 评测基线](docs/agent-evaluation.md)。
