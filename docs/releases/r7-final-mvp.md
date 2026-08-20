# Riverline R7 Final MVP

## 发布结论

R7 源码 MVP 的功能验收已达到标准：用户可在持续六人桌连续完成牌局，Hero 决策控件不会在 Bot 过渡后锁死；终局展示、复盘/统计与下一手状态切换可用；Advisor、Range V2 与 Fast Solver L1.5 在同一决策视图中同时提供信息。PR #3 暴露的 CI 性能门已在本分支窄修复并通过 focused tests，但该修复仍需独立缓存/隐私窄审与 GitHub CI 复跑，完成前本修订不作为最终源码发布结论。

本结论只覆盖 GitHub 源码候选。它不创建 GitHub Release、Docker image、wheel、安装包或包含 `node_modules` 的二进制制品。

## 已交付能力

- 持续 6-max 人机牌桌：随机发牌、公开行动、Bot 可读节奏与非单一策略、清台补码、终局 show、下一手及断线重连。
- Always-on Advisor：在 Hero 合法决策点快速返回公式/规则驱动建议，并明确其不是 Solver 或 GTO 结论。
- Range V2：以 1,326 个组合维护只依赖公开事件与 Hero 可见 blocker 的独立座位 belief，再投影为 169 格视图；输出范围宽度、置信度、变化理由与启发式来源。
- Fast Solver L1.5：使用公开 Range V2、全局牌张唯一性、合法候选尺寸和有界 Monte Carlo/启发式响应模型输出近似 EV、胜率、置信区间与来源。
- 自动复盘闭环：终局后提供 review/stats，进入下一手时不保留上一决策的旧异步结果。

## R7-08 发布门

发布门基线：`adcf2eb65eefc3ed3627bde1b2101fb64b78b303`，分支：`codex/r7-08-release`。

- Backend：本地发布门在无 PostgreSQL 服务的环境中退出成功，`compileall` 与 `pip check` 通过。随后 PR #3 的 GitHub CI run `32358541597` 实际运行全部 599 项，结果为 598 passed、0 skipped、1 个 Range 性能门失败，因此 live PostgreSQL 路径已实测通过。
- Frontend：32 files / 167 tests passed；`npx tsc --noEmit` 通过；标准 `npm run build`（Next.js 16 Turbopack）通过。
- License：`py -3.13 tools/generate_license_provenance.py --check` 通过。
- Browser：`continuous-table`、`local-experience`、`r7-golden-journey`、`table-v2-visual` 共 4 个 Playwright 测试通过。双手黄金旅程在 4.3 秒内完成，并覆盖实时洞察、终局、下一手、隐私和旧状态隔离。
- Local runtime：`scripts/run-local.ps1` 在 SQLite/no-Redis 默认模式启动成功；同一专用端口停止后重启成功，API `/health` 返回 `ok`，Web 返回 HTTP 200。

### PR #3 CI 性能修订

GitHub runner 上，原 Range V2 benchmark 测得 p50 `35.667ms`、p95 `49.491ms`：p95 满足冻结的 `<50ms` 门，但 p50 未满足冻结的 `<25ms` 门。该失败未被改成 skip/xfail，也没有放宽产品阈值。

窄诊断确认两个直接缓存热点：同一不可变 combo 分布因快照 metadata 不同而重复生成 169 projection；折牌 seat 在相邻决策重放时重复复制等价 inactive 快照，破坏后续 blocker/projection 缓存命中。修复为有界、带对象身份守卫的不可变结果复用，并新增两个先红后绿的回归测试。修复后同一完整 19-event/16-action/5-opponent benchmark 本机 p50 `2.095ms`、p95 `2.307ms`，Range V2 focused suite `86 passed`。修复提交后的 GitHub CI 复跑尚未由本任务实测。

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
- Live PostgreSQL 已由 PR #3 GitHub CI 实测通过；本地 SQLite/no-Redis 纵向路径仍独立通过。修复提交后的完整 CI 复跑尚未执行，不能继承为通过。
- 仓库声明 Node.js `24.15.0`，本机实测为 `24.18.0`；测试与构建均通过，该补丁版本差异记录为非阻塞环境偏差。
