# Riverline R7 Current Snapshot

## 发布范围

这是 GitHub 源码快照候选，不创建 GitHub Release、Docker image、wheel、安装包或含 `node_modules` 的二进制制品。

当前可本地体验的主入口是默认持续六人桌：创建牌桌、观察 Bot 行动、执行 Hero 合法行动、断线重连、开始下一手，以及完成手牌的复盘入口。页面提供明确的 Advisor 摘要、位置/公开行动驱动的 Range Belief 169 格热图和 Fast Solver 近似 EV 结果；这些区域均明确其启发式/近似与私牌边界。

使用 `./scripts/run-local.ps1` 启动默认 SQLite、无 Redis 的本地模式。它只对自身子进程屏蔽 `.env` 中的外部 PostgreSQL/Redis 设置；`-UseExternalServices` 才继承外部服务配置。脚本会打印本地 URL 和日志目录。替代端口也受支持，例如 `./scripts/run-local.ps1 -ApiPort 8100 -WebPort 3100`。

## 验证

R7 发布门在 `codex/r7-current-snapshot-release` 上针对 `e7ae8e83aa8392085465d71fa89c980d31ab40ae` 运行：

- backend 完整测试通过，包含 10 个既有、环境驱动的 live PostgreSQL/Redis skips；`py -3.13 -m compileall -q backend` 与 `py -3.13 -m pip check` 通过。
- frontend 完整单元测试通过（32 files / 165 tests），`npx tsc --noEmit` 与 `npm run build` 通过。
- 隔离的 SQLite/no-Redis 服务（8103/3103）通过 `continuous-table` 和 `local-experience` Playwright smoke：健康在线、六席牌桌、Hero 手牌和合法操作、Advisor、Range 的隐私说明与 Solver 均可见。
- `py -3.13 tools/generate_license_provenance.py --check` 通过。

## 已知边界

- Range 仍为当前 V1 的第一方、位置/筹码桶启发式先验与公开事件更新；不是 GTO、玩家画像或联合对手范围。
- Solver 仍为当前 L1 的 Fast Solver 近似 EV；不是 GTO/Nash，且其已显示限制必须随结果一并理解。
- R7-03（Range V2）、R7-04、R7-05、R7-06 延期，不属于本快照。
- source repository release 可由 provenance gate 评估；含原生依赖的 bundled binary/container 仍需单独完成 LGPL 工件义务核验，未在本次构建或发布。
