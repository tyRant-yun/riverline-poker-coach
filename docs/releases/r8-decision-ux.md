# R8 Decision UX source MVP 发布门

日期：2026-08-20  
分支：`codex/r8-release`  
精确基线：`7ccbc2d43e8f3271cfe0a3225c0bf39d6b0396b8`  
发布门 delivery：`82cde45027bb4ac16457ab467afca7dfd0ae894a`

## 结论

- `source_release_ready: false`
- `binary_or_container_release_ready: false`
- `license_source_repository_release: PASS`
- `release_gate_status: BLOCKED`

R8 功能、构建、本地启动与产品交互证据在本地 SQLite/no Redis 范围内闭合，且没有遗留的已知功能 P0/P1。发布仍被一个新发现的依赖安全 P1 阻塞：`npm audit --json` 报告 3 个 high severity 依赖项（直接依赖 `next@16.1.0`，以及其 `postcss`、`sharp` 传递链），npm 给出的可用修复是 `next@16.3.1`。本任务明确禁止依赖升级，因此没有修改 `package.json` 或 lockfile，也没有把 source release 宣称为可发布。

另外，发布门发现并最小修复了一个 Range Explorer 可操作性 P1：overlay 的 `z-index:20` 低于 sticky app header 的 `z-index:50`，1280×720 下关闭按钮会被 header 截获。修复把 overlay 提升至 `z-index:60`，focused 当前产品 E2E 已通过；在合并或发布前仍需对 `82cde45027bb4ac16457ab467afca7dfd0ae894a` 做独立窄审。

## 质量门实测

| 范围 | 原始命令 | 结果 |
|---|---|---|
| Backend 完整测试 | `cd backend; py -3.13 -m pytest -q` | 621 collected；611 passed；10 个 live PostgreSQL 测试在本地服务范围跳过；退出 0。 |
| Python 编译 | `py -3.13 -m compileall -q backend/poker_coach` | 退出 0。 |
| Python 依赖 | `py -3.13 -m pip check` | `No broken requirements found.` |
| License/source 边界 | `py -3.13 tools/generate_license_provenance.py --root . --check` | `PASS`；已提交 SBOM 含 296 components；`source_repository_release=PASS`。 |
| Frontend unit | `cd frontend; npm test` | 32 files / 174 tests passed。 |
| TypeScript | `cd frontend; npm run lint` | `tsc --noEmit` 退出 0。 |
| Production build | `cd frontend; npm run build` | Next 16 production build passed；`next-env.d.ts` 的 dev/build 生成改写已恢复，未进入 Git diff 或提交。 |
| 完整当前产品 Playwright | `PLAYWRIGHT_BASE_URL=http://127.0.0.1:13880 npx playwright test` | 5 passed / 2 failed。失败均为旧 E2E 契约漂移：旧 Solver 文案、已移除的 `skip` Bot speed option；未重复完整套件。 |
| 失败项 focused 修订 | `PLAYWRIGHT_BASE_URL=http://127.0.0.1:13880 npx playwright test e2e/mvp-shell.spec.ts e2e/r7-golden-journey.spec.ts` | `mvp-shell` passed；golden journey 因第二处旧英文 `Solver` 断言失败。 |
| 真实两手 focused 终态 | `PLAYWRIGHT_BASE_URL=http://127.0.0.1:13880 npx playwright test e2e/r7-golden-journey.spec.ts` | 1 passed，3.5s；真实 SQLite/no Redis 服务完成连续两手、Hero action、Advisor/Range/Solver 可用性、next hand、reload/reconnect 与私牌不泄漏检查。 |
| R8 受控产品证据 | `PLAYWRIGHT_BASE_URL=http://127.0.0.1:13880 npx playwright test e2e/r8-release-gate.spec.ts` | focused 终态 1 passed；完整 Playwright 中同项也 passed。覆盖 Bot seat action pill/dwell、Advisor/模拟估计分歧、Solver 全部尺度、Range Explorer、showdown、next hand、reconnect 与终局私牌清理。 |
| 依赖安全 | `cd frontend; npm audit --json` | 退出 1；3 high / 0 critical。直接 `next@16.1.0` 与传递 `postcss`、`sharp`；fix available 指向 `next@16.3.1`。阻塞 source release。 |

完整 Playwright 没有在测试修订后重跑，这是“一次且仅一次完整门”的明确约束。终态证据由完整套件中已通过的 5 项，加两项失败 spec 的 focused 终态通过组成；本报告不把它伪写成一次 7/7 的 post-repair 完整运行。

## 本地启动与清理

执行：

```powershell
scripts/run-local.ps1 -ApiPort 18880 -WebPort 13880 -StartupTimeoutSeconds 120
```

实测事实：

- 模式：默认 SQLite + no Redis，未使用 `-UseExternalServices`。
- API：`http://127.0.0.1:18880/health` 返回 200，body `status=ok`。
- Web：`http://127.0.0.1:13880` 返回 200。
- 启动根 PID：API `7396`，Web `14424`；仅清理这两个已核对根 PID 的子进程树。
- 清理后：18880 与 13880 的监听数均为 0，两个根 PID 均不存在。

## R8 产品证据

受控 Playwright 使用真实当前产品组件与确定性网络 fixture，属于 automated interaction proxy，不是人类可用性研究。计时从可决策桌面稳定后开始：

| 任务 | 完整 Playwright 实测 | 阈值 |
|---|---:|---:|
| 定位并打开 Range Explorer | 84ms | ≤5000ms |
| 定位 Solver 首选并展开全部 5 个尺度 | 56ms | ≤5000ms |
| 定位 Advisor/Solver 分歧及原因 | 14ms | ≤5000ms |

同一受控路径还验证：

- Advisor 明确标为“规则基线”，Solver 明确标为“模拟估计”，分歧原因显示为“模型限制”，不做前端最终仲裁。
- Solver 首选、pot%、筹码、EV、ΔEV CI、接近/极端尺度与全部尺度展开均来自 DTO fixture 的公开字段。
- Range Summary 显示范围宽度、置信度、主要牌类；Explorer 169 格可展开并可实际关闭。
- Bot 先显示 seat thinking，再显示 action pill；浏览器内 MutationObserver 断言可感知 dwell 不低于 700ms，随后 Hero 控件在 200ms 断言窗口内恢复。
- 受控 showdown 只在终局显示对手 reveal，下一手和 reload/reconnect 后清除；非终局始终只有 Hero 的 hole-card 容器。
- 1366×768、1440×900、1920×1080 与 1280×720 窄桌面当前产品 surface 均无水平页面滚动；静态 geometry/Explorer spec 同样通过。

真实服务 golden journey 与受控证据的边界保持诚实：真实服务 spec 覆盖连续两手牌和 API/状态闭环，但牌局可以由弃牌结束，不强制生成 showdown；showdown reveal 与 dwell 的确定性断言由受控当前产品 spec 提供。

## 已继承审查与未实测项

- 整体双轴审查由上游完成：Standards hard findings = 0；Spec P0/P1 = 0。该结果是本任务输入，不是本发布 Worker 重复执行的审查。
- 本任务新增 `82cde45` 后，需要独立窄审 Range Explorer 层级修复与发布 E2E，不得把上游审查结果继承为对新 diff 的审查。
- live PostgreSQL、外部 Redis、二进制/容器实际捆绑、对应源码/notice 处理未实测。
- 仓库要求 Node `24.15.0`；本机实测为 Node `24.18.0`，因此精确 Node engine 验证未完成。
- 没有人类参与 5 秒任务；这里只报告自动化操作代理。
- `npm audit` 安全阻塞未修复；本任务禁止依赖升级。

## Binary/container 边界

`docs/provenance/sbom.json` 的 `bundled_binary_container_release=FAIL`。主要原因是 npm/Python 组件缺少可验证的 binary artifact integrity hash，以及各平台 `sharp/libvips` 实际捆绑二进制、notice 与 corresponding-source 处理尚未验证。因此禁止发布捆绑二进制或容器，与 source license verdict PASS 相互独立。

## 解锁条件

1. Controller/产品负责人授权独立依赖升级任务，将 Next 升级至包含 npm advisory 修复的版本（npm 当前建议 `16.3.1`），按受影响范围重跑 unit、tsc、build、当前产品 Playwright、license provenance 与 `npm audit`。
2. 独立窄审 `82cde45027bb4ac16457ab467afca7dfd0ae894a`，确认 Range Explorer 层级修复与测试没有 P0/P1。
3. 只有安全审计无阻塞 high/critical 且窄审通过后，才能把 `source_release_ready` 改为 `true`。
4. Binary/container 发布继续保持禁止，直到 SBOM 中对应 verdict 独立转为 PASS。
