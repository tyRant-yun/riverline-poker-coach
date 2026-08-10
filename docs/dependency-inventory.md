# 依赖与许可证清单

更新时间：2026-08-10

## 当前盘点

当前已引入并锁定 Python API 依赖和 Next.js 前端依赖。Python 锁定文件为 [`backend/requirements.lock`](../backend/requirements.lock)，前端锁定文件为 [`frontend/package-lock.json`](../frontend/package-lock.json)，项目声明分别见 [`backend/pyproject.toml`](../backend/pyproject.toml) 和 [`frontend/package.json`](../frontend/package.json)。

| 包 | 类型 | 版本 | 许可证 | 用途 |
|---|---|---:|---|---|
| pydantic | 直接运行时 | 2.13.4 | MIT | 领域合同校验和序列化 |
| fastapi | 直接运行时 | 0.139.2 | MIT | HTTP API 和请求校验边界 |
| uvicorn | 直接运行时 | 0.51.0 | BSD-3-Clause | 本地 ASGI 服务启动 |
| psycopg | 可选 PostgreSQL 运行时 | 3.3.4 | LGPL-3.0-only | PostgreSQL DB-API 适配层 |
| psycopg-binary | 可选 PostgreSQL 运行时 | 3.3.4 | LGPL-3.0-only | 无本地 libpq 的预编译驱动 |
| httpx | 测试组直接依赖 | 0.28.1 | BSD-3-Clause | FastAPI TestClient 测试传输 |
| pytest | 测试组直接依赖 | 9.1.1 | MIT | Python 单元测试 |
| pokerkit | 直接规则依赖 | 0.7.4 | MIT | MVP 牌局规则、合法动作和牌面状态 |
| pydantic-core | 间接 | 2.46.4 | MIT | Pydantic 核心校验 |
| annotated-types | 间接 | 0.8.0 | MIT | 类型约束元数据 |
| typing-extensions | 间接 | 4.16.0 | PSF-2.0 | Python 类型兼容 |
| typing-inspection | 间接 | 0.4.2 | MIT | 类型检查支持 |
| colorama | 测试间接 | 0.4.6 | BSD-3-Clause | Windows 测试终端输出 |
| iniconfig | 测试间接 | 2.3.0 | MIT | Pytest 配置解析 |
| packaging | 测试间接 | 26.2 | Apache-2.0 OR BSD-2-Clause | 版本解析 |
| pluggy | 测试间接 | 1.6.0 | MIT | Pytest 插件机制 |
| Pygments | 测试间接 | 2.20.0 | BSD-2-Clause | 测试输出高亮 |
| Next.js | 前端直接运行时 | 16.1.0 | MIT | Web App Router 和页面服务 |
| React | 前端直接运行时 | 19.2.0 | MIT | 前端 UI |
| react-dom | 前端直接运行时 | 19.2.0 | MIT | React 浏览器渲染 |
| @playwright/test | 前端测试依赖 | 1.62.1 | Apache-2.0 | Chromium 浏览器端到端测试 |
| TypeScript | 前端开发依赖 | 5.9.3 | Apache-2.0 | 类型检查和构建 |

许可证以本地发行包元数据或随包许可证文件为准；缺失 SPDX 字段的包已按其发行包声明核对，并应在 CI 依赖审计中再次验证。

## 计划依赖边界

以下是架构计划，不代表已经安装；添加到 manifest 前必须锁定具体版本并核验许可证：

| 领域 | 候选组件 | 引入条件 |
|---|---|---|
| Web | Next.js、React、TypeScript | 已引入本地前端切片和 E2E |
| 前端数据 | TanStack Query | API 契约稳定后 |
| API | FastAPI、Pydantic | 已引入；业务逻辑仍保持在领域/分析层 |
| 规则 | PokerKit | 适配层和金标牌谱准备后；MVP 唯一正式规则源 |
| 数据库 | SQLite（标准库）、psycopg | SQLite 已用于本地持久化；PostgreSQL 由可选适配层支持 |
| 缓存/任务 | Redis 客户端和轻量任务队列 | 需要异步分析或缓存时 |
| 测试 | Pytest、Playwright | 已引入；Vitest 仍待有独立前端单元逻辑时评估 |

## 许可证政策

- 每次新增或升级依赖必须记录名称、版本、许可证、来源和用途。
- 直接依赖和锁文件解析出的间接依赖都必须进入自动化清单。
- 必须标记 MIT、Apache-2.0、BSD、AGPL 等许可证，并在引入前审查传染性义务。
- **项目定位**：用户明确本项目**非商用、无收益**，可以适当放宽复用边界（2026-08-10 确认）。但注意 AGPL 的传染性义务**不以商用为前提**：无论是否营利，把 AGPL 代码并入本项目都会要求合并作品按 AGPL 分发并提供源码。**已选定路径：隔离服务路径**——AGPL 引擎（`b-inary/postflop-solver`）作为独立 sidecar 进程/HTTP 服务运行，与主项目仅通过 API 交互（不构成衍生作品），主项目保持宽松许可；solver 输出数据（求解结果 JSON）不属于代码，可自由导入。若未来公开分发或部署给第三方使用，需另行处理 AGPL 义务。
- 许可干净、可直接复用的候选：TexasHoldemSolverJava（MIT）、rs-poker（Apache-2.0）、krukah/robopoker（MIT，MCTS，仅训练桌 bot 方向，当前不采用）。求解引擎最终选型：postflop-solver（AGPL，sidecar 隔离服务，见 docs/solver-integration-design.md）；TexasSolver 为 B 方案。
- 路径已选定（2026-08-10）：AGPL 引擎以 sidecar 隔离服务形态引入，其源码只存在于独立进程/独立容器，不进主项目仓库与依赖清单（ADR-0004、docs/solver-integration-design.md）。
- OpenSpiel、RLCard 不进入生产部署依赖；研究验证放在隔离环境并单独记录。
- 上游版本升级必须重新跑金标牌谱、属性测试和许可证检查。

## 待办

1. 用锁文件生成直接/间接依赖报告并接入 CI。
2. 为前端补充 Vitest 前再评估测试依赖。
3. 为 CI 增加许可证清单检查和 AGPL 源码扫描。
4. 在 PokerKit 版本固定后记录其 API 适配范围和回归结果。
