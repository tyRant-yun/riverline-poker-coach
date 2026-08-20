# Riverline R7 Final MVP

## 发布结论

R7 源码 MVP 已达到验收标准：用户可在持续六人桌连续完成牌局，Hero 决策控件不会在 Bot 过渡后锁死；终局展示、复盘/统计与下一手状态切换可用；Advisor、Range V2 与 Fast Solver L1.5 在同一决策视图中同时提供信息。

本结论只覆盖 GitHub 源码候选。它不创建 GitHub Release、Docker image、wheel、安装包或包含 `node_modules` 的二进制制品。

## 已交付能力

- 持续 6-max 人机牌桌：随机发牌、公开行动、Bot 可读节奏与非单一策略、清台补码、终局 show、下一手及断线重连。
- Always-on Advisor：在 Hero 合法决策点快速返回公式/规则驱动建议，并明确其不是 Solver 或 GTO 结论。
- Range V2：以 1,326 个组合维护只依赖公开事件与 Hero 可见 blocker 的独立座位 belief，再投影为 169 格视图；输出范围宽度、置信度、变化理由与启发式来源。
- Fast Solver L1.5：使用公开 Range V2、全局牌张唯一性、合法候选尺寸和有界 Monte Carlo/启发式响应模型输出近似 EV、胜率、置信区间与来源。
- 自动复盘闭环：终局后提供 review/stats，进入下一手时不保留上一决策的旧异步结果。

## R7-08 发布门

发布门基线：`adcf2eb65eefc3ed3627bde1b2101fb64b78b303`，分支：`codex/r7-08-release`。

- Backend：完整测试收集 599 项，589 passed、10 个既有 live PostgreSQL/Redis 环境测试 skipped；`compileall` 与 `pip check` 通过。
- Frontend：32 files / 167 tests passed；`npx tsc --noEmit` 通过；标准 `npm run build`（Next.js 16 Turbopack）通过。
- License：`py -3.13 tools/generate_license_provenance.py --check` 通过。
- Browser：`continuous-table`、`local-experience`、`r7-golden-journey`、`table-v2-visual` 共 4 个 Playwright 测试通过。双手黄金旅程在 4.3 秒内完成，并覆盖实时洞察、终局、下一手、隐私和旧状态隔离。
- Local runtime：`scripts/run-local.ps1` 在 SQLite/no-Redis 默认模式启动成功；同一专用端口停止后重启成功，API `/health` 返回 `ok`，Web 返回 HTTP 200。

## 本地体验

在仓库根目录执行：

```powershell
.\scripts\run-local.ps1
```

如默认端口已占用：

```powershell
.\scripts\run-local.ps1 -ApiPort 8100 -WebPort 3100
```

脚本会打印 API/Web 地址、PID 与日志目录；默认只为它启动的子进程屏蔽外部 PostgreSQL/Redis 环境，且不会修改 `.env`。体验结束后停止脚本列出的进程。

## 诚实边界

- Solver L1.5 是 bounded range-aware Monte Carlo / heuristic EV，不是 GTO、Nash、CFR 或多街博弈树求解器。
- Range V2 是第一方公开事件启发式独立边际 belief，不是校准人群模型、玩家画像或联合对手范围。
- R7-06 HU River CFR/L2 已延期，不阻塞本次 MVP。
- 源码仓库 provenance gate 已通过；包含原生依赖的 binary/container 仍需单独核验 LGPL 工件义务，本次未发布此类制品。
- Live PostgreSQL/Redis 未在本次发布门中实测；相关 10 项测试保持 `measured: false`/skipped。
- 仓库声明 Node.js `24.15.0`，本机实测为 `24.18.0`；测试与构建均通过，该补丁版本差异记录为非阻塞环境偏差。
