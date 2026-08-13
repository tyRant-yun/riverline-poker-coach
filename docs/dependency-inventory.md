# 依赖与许可证清单

更新时间：2026-08-12

> 当前权威台账为根目录 [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md)。可重复的 resolved inventory 是 [`provenance/sbom.json`](provenance/sbom.json)，人类可读报告是 [`provenance/THIRD_PARTY_NOTICES.md`](provenance/THIRD_PARTY_NOTICES.md)；许可治理以 ADR-0008 为准。

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

- Riverline 仓库采用 `AGPL-3.0-or-later`；非商用/无收益不放宽 GPL/AGPL 义务。
- 每次新增或升级依赖必须记录名称、精确版本/commit、许可证、来源、用途、完整性 hash、修改和决策证据。
- 直接依赖和锁文件解析出的间接依赖都必须进入发布 SBOM/NOTICE 清单。
- 进程、容器和 HTTP 边界只作故障/部署隔离，不声明自动解决许可证组合判断。
- `postflop-solver` 等 AGPL solver 不进入主依赖图，只能作为有完整源码、构建、修改与 artifact provenance 的可选研究 producer；任何发布/网络使用另行审查。
- OpenSpiel、RLCard、PettingZoo 不进入在线规则依赖；研究验证使用隔离环境和独立锁定。
- 上游版本升级必须重新跑金标牌谱、属性/差分测试和许可证检查。

## 发布范围与复核

在仓库根目录运行 `py -3.13 tools/generate_license_provenance.py --check`。它不联网、不安装包，并从 `backend/pyproject.toml`、`backend/requirements.lock`、受控 Python distribution metadata 和 `frontend/package-lock.json` 生成确定性 SBOM/NOTICE 报告。

- `source_repository_release`：适用于只提交 Git 源码和锁文件的 GitHub 分支/PR 合并。要求准确版本、license 与 source/provenance；lockfile 中已有的 npm integrity 会被记录；未知 license/source、禁止的 GPL/AGPL runtime 依赖和无人工决定的 copyleft 条目均 fail-closed。
- `bundled_binary_container_release`：适用于 Docker image、wheel、安装包或其他携带二进制的制品。除 source gate 外，还要求实际 artifact hash 与制品的 NOTICE/source 义务。当前为 FAIL：Python lock 未固定 artifact hashes，且 sharp/libvips 二进制的实际分发义务尚未逐制品核验。

## 待办

1. 用锁文件生成直接/间接依赖报告并接入 CI。
2. 为前端补充 Vitest 前再评估测试依赖。
3. 为 CI 增加许可证清单检查和 AGPL 源码扫描。
4. 在 PokerKit 版本固定后记录其 API 适配范围和回归结果。
