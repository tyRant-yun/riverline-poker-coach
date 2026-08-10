# 安全、隐私与运维边界

## 输入安全

- ScenarioSpec、牌、金额、范围和 ActionEvent 全部由服务端 Pydantic 与 PokerKit 适配层校验；前端按钮不是安全边界。
- API 请求体默认限制为 1 MiB；单次分析超时默认最多 120 秒；Monte Carlo 默认最多 1,000,000 次试验。范围和其他 Equity 工作量也受领域模型与 Equity 引擎上限约束。
- 匿名 API 默认按会话或客户端地址限流，每分钟 120 个请求；生产环境应改用网关或 Redis 限流，`POKER_COACH_RATE_LIMIT_PER_MINUTE=0` 只用于本地测试。
- 用户问题和备注按不可信数据处理，不作为系统指令；当前教学服务不把自由文本拼接进规则或数值计算。
- `Idempotency-Key` 可用于重复分析请求；同一键绑定不同场景会返回 `idempotency_conflict`。

## 隐私

- 本地默认数据库为 `.data/poker_coach.sqlite3`，已加入 Git 忽略规则。
- 学习画像使用匿名 profile ID；删除场景会级联清理关联分析和教学会话，删除 profile 会级联清理练习、尝试、概念进度和教学记录。
- 日志和响应不记录密钥；自由文本不进入规则证据或策略事实。
- 教学问题默认不写入 `teaching_sessions.user_question`；只有显式设置 `POKER_COACH_STORE_USER_TEXT=1` 才会持久化用户自由文本。
- 生产部署仍需补充认证、限流、加密备份和跨用户授权，不应直接暴露当前匿名本地 API。

## 可观测性与失败降级

- HTTP 响应带 `X-Request-ID`，健康检查和版本接口返回规则/分析版本。
- API 请求完成日志通过 `poker_coach.api` logger 输出 requestId、方法、路径、状态、耗时、scenarioHash、匿名会话标识和缓存命中；不记录请求正文或密钥。
- 分析结果保存场景哈希、规则版本、分析版本、随机种子、执行时间、EvidenceBundle 和状态。
- 场景修订和分析运行绑定具体 revision；历史 revision 可以单独重新分析，原始与标准化 JSON 快照分开保存。
- `/v1/analysis/equity` 只返回由分析核心生成的 Equity 和 EvidenceBundle，不允许客户端或教学层自行计算数值。
- 策略无匹配时仍返回规则、数学和牌力证据；Equity 超时或教学失败不得伪造策略频率。
- 当前幂等缓存是进程内缓存；多进程部署必须替换为 Redis 或持久化幂等存储。
- `/v1/analysis/jobs` 提供本地进程内提交、轮询和取消；生产部署需要外置任务队列、资源配额和跨进程取消。

可调安全配置：`POKER_COACH_MAX_REQUEST_BYTES`、`POKER_COACH_MAX_TIMEOUT_SECONDS`、`POKER_COACH_RATE_LIMIT_PER_MINUTE`。修改超时上限不能替代任务队列的资源隔离。

## 本地运维

```powershell
python -m pytest
python -m compileall -q backend/poker_coach backend/tests
python -m pip check
cd frontend
node node_modules/typescript/bin/tsc --noEmit -p tsconfig.json
node node_modules/next/dist/bin/next build
```

备份本地数据时复制 `.data/poker_coach.sqlite3`；恢复前停止 API 进程。PostgreSQL 迁移和 Redis 任务部署属于后续阶段，当前 SQLite schema 是其逻辑模型的本地实现。

PostgreSQL 集成使用 `POKER_COACH_DATABASE_URL` 和可选的 `psycopg[binary]` 依赖；启动前必须执行 schema 初始化并为数据库账号配置最小权限。不要把连接串提交到 `.env` 以外的版本控制文件。
