# 依赖与许可证清单

更新时间：2026-08-09

## 当前盘点

领域核心已引入并锁定 Python 依赖；前端、FastAPI、数据库和 Redis 尚未引入。锁定文件为 [`backend/requirements.lock`](../backend/requirements.lock)，项目声明为 [`backend/pyproject.toml`](../backend/pyproject.toml)。

| 包 | 类型 | 版本 | 许可证 | 用途 |
|---|---|---:|---|---|
| pydantic | 直接运行时 | 2.13.4 | MIT | 领域合同校验和序列化 |
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

许可证以本地发行包元数据或随包许可证文件为准；缺失 SPDX 字段的包已按其发行包声明核对，并应在 CI 依赖审计中再次验证。

## 计划依赖边界

以下是架构计划，不代表已经安装；添加到 manifest 前必须锁定具体版本并核验许可证：

| 领域 | 候选组件 | 引入条件 |
|---|---|---|
| Web | Next.js、React、TypeScript | 开始前端切片时；提交 npm 锁文件 |
| 前端数据 | TanStack Query | API 契约稳定后 |
| API | FastAPI、Pydantic | 领域合同通过基础测试后 |
| 规则 | PokerKit | 适配层和金标牌谱准备后；MVP 唯一正式规则源 |
| 数据库 | PostgreSQL 驱动和迁移工具 | 场景持久化切片时 |
| 缓存/任务 | Redis 客户端和轻量任务队列 | 需要异步分析或缓存时 |
| 测试 | Pytest、Vitest、Playwright | 对应代码切片落地时 |

## 许可证政策

- 每次新增或升级依赖必须记录名称、版本、许可证、来源和用途。
- 直接依赖和锁文件解析出的间接依赖都必须进入自动化清单。
- 必须标记 MIT、Apache-2.0、BSD、AGPL 等许可证，并在引入前审查传染性义务。
- 不复制或直接集成 TexasSolver、postflop-solver 的 AGPL 源代码；它们只能作为行为和界面参考。
- OpenSpiel、RLCard、RoboPoker、rs-poker 不进入 MVP 生产部署依赖；研究验证要放在隔离环境并单独记录。
- 上游版本升级必须重新跑金标牌谱、属性测试和许可证检查。

## 待办

1. 为前端和 API 创建 manifest，并固定版本与锁文件。
2. 用锁文件生成直接/间接依赖报告。
3. 为 CI 增加许可证清单检查和 AGPL 源码扫描。
4. 在 PokerKit 版本固定后记录其 API 适配范围和回归结果。
