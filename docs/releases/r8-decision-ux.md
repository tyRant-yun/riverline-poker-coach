# R8 Decision UX source MVP 发布门

日期：2026-08-20  
分支：`codex/r8-release`  
精确集成基线：`7ccbc2d43e8f3271cfe0a3225c0bf39d6b0396b8`
首轮发布门 delivery：`82cde45027bb4ac16457ab467afca7dfd0ae894a`
依赖安全 follow-up delivery：`1e6dee37e59d9b72f7098939508f4e259dbeb326`

## 结论

- `source_release_ready: pending_independent_review_and_ci`
- `binary_or_container_release_ready: false`
- `license_source_repository_release: PASS`
- `release_gate_status: PENDING_INDEPENDENT_REVIEW_AND_CI`

首轮发布门发现的 source security P1 已在极窄授权范围内本地关闭：唯一直接依赖变更是 `next` 从精确版本 `16.1.0` 升至 `16.3.1`，React/React DOM 保持 `19.2.0`。lockfile 实际解析为 Next/PostCSS/Sharp `16.3.1/8.5.23/0.35.3`；`npm audit --audit-level=high` 终态为 `found 0 vulnerabilities`。完整 frontend unit、tsc、production build 与当前产品 Playwright 均通过。

这不是最终发布声明。仓库要求 Node `24.15.0`，本机实测为 `24.18.0`；此外依赖 delivery 与发布 E2E 仍需独立窄审。只有独立审查与 GitHub CI 精确环境门均通过后，Controller 才能把 source readiness 改为最终 PASS。

Binary/container publication 继续明确禁止。更新后的 SBOM source verdict 为 PASS，但 bundled binary/container verdict 仍为 FAIL。

## 依赖安全修复

升级前在 `27f7e6ad45a1af7a93745b0482dd92c39aa043c2` 实测：

```text
npm audit --audit-level=high --json
exit 1; high=3; critical=0
next@16.1.0 (direct), postcss<=8.5.22, sharp<0.35.0
fixAvailable: next@16.3.1
```

升级后实测安装树：

| Package | Version |
|---|---:|
| next | 16.3.1 |
| @next/env | 16.3.1 |
| @next/swc-win32-x64-msvc | 16.3.1 |
| postcss（Next chain） | 8.5.23 |
| sharp | 0.35.3 |
| react | 19.2.0 |
| react-dom | 19.2.0 |

`npm ls next postcss sharp react react-dom --depth=1` 退出 0。精确终态命令 `npm audit --audit-level=high` 退出 0，输出 `found 0 vulnerabilities`。

在线 clean install 遇到下载层瞬态：Next/SWC/Sharp 平台包通过 registry 的速度异常缓慢，多次安装在无 package error 的下载阶段被受控中止；IPv4 优先下载后本地缓存完整，`npm ci --offline --ignore-scripts --no-audit --no-fund` 成功安装 178 packages，随后显式安装 lockfile 已含的 Windows SWC 16.3.1 可选包。production build 和完整 Playwright 证明实际平台运行时可用。GitHub CI 仍是干净网络与精确 Node 24.15.0 的最终门。

## 质量门实测

| 范围 | 原始命令 | 结果 |
|---|---|---|
| Backend 完整测试（首轮发布门） | `cd backend; py -3.13 -m pytest -q` | 621 collected；611 passed；10 个 live PostgreSQL 测试在本地服务范围跳过；退出 0。Frontend-only 安全 follow-up 未重复 backend。 |
| Python 编译/依赖（首轮发布门） | `py -3.13 -m compileall -q backend/poker_coach`; `py -3.13 -m pip check` | 退出 0；`No broken requirements found.` |
| License/source 边界（升级后） | `py -3.13 tools/generate_license_provenance.py --root .`; `py -3.13 tools/generate_license_provenance.py --root . --check` | 生成器与 `--check` 均 PASS；298 components；`source_repository_release=PASS`；`bundled_binary_container_release=FAIL`。 |
| Frontend unit（升级后） | `cd frontend; npm test` | 32 files / 174 tests passed。 |
| TypeScript（升级后） | `cd frontend; npm run lint` | `tsc --noEmit` 退出 0。 |
| Production build（升级后） | `cd frontend; npm run build` | Next 16.3.1 production build passed；`next-env.d.ts` 生成改写未进入 delivery。 |
| R8 E2E focused（证据修订后） | `PLAYWRIGHT_BASE_URL=http://127.0.0.1:13880 npx playwright test e2e/r8-release-gate.spec.ts` | 首次因 SWC 首次下载未完成导致 `page.goto` 35s `ERR_ABORTED/frame detached`，未执行产品断言；SWC 安装完成后 1 passed / 4.8s，代理 54/42/10ms。 |
| 当前产品完整 Playwright（升级后） | `PLAYWRIGHT_BASE_URL=http://127.0.0.1:13880 npx playwright test` | 7/7 passed，10.4s；真实两手 journey 2.7s；R8 代理 58/37/9ms。 |
| 依赖安全（升级后） | `cd frontend; npm audit --audit-level=high` | 退出 0；`found 0 vulnerabilities`。 |

## 本地启动与清理

完整 Playwright 使用：

```powershell
scripts/run-local.ps1 -ApiPort 18880 -WebPort 13880 -StartupTimeoutSeconds 120
```

- 默认 SQLite + no Redis，未使用外部服务。
- API `/health` 与 Web 均返回 HTTP 200。
- 本次升级后完整门启动根 PID 为 API `27716`、Web `16372`；仅清理这两个已核对根 PID 的子进程树。
- 清理后 18880/13880 监听数均为 0。
- Next dev 自动生成的 `frontend/AGENTS.md`、`frontend/CLAUDE.md` 与 `next-env.d.ts` dev import 均作为运行副作用清理，未提交。

## R8 产品与窄审证据

受控 Playwright 使用真实当前产品组件与确定性网络 fixture，属于 automated interaction proxy，不是人类可用性研究。升级后完整 Playwright 计时：

| 任务 | 实测 | 阈值 |
|---|---:|---:|
| 定位 Range Summary、识别 Top mover 状态并打开 Range Explorer | 58ms | ≤5000ms |
| 定位 Solver 首选并展开全部 5 个尺度 | 37ms | ≤5000ms |
| 定位 Advisor/Solver 分歧及原因 | 9ms | ≤5000ms |

Range fixture 没有同手上一快照，因此不伪造 Top mover；计时任务明确断言用户可见的诚实解释：`Top movers 暂不可用：需同手、同座位的上一公开行动 Range 快照。`

每个 1366×768、1440×900、1920×1080 与 1280×720 窄桌面都逐一断言：

- Hero seat 在牌桌水平中置且可见；Hero action 可达。
- Decision Summary 在初始 viewport 可达。
- Solver 默认候选精确为前三行，三行均在 viewport 可达。
- Range Summary 在初始 viewport 可达。
- 页面无水平滚动。

同一路径继续覆盖 Bot seat thinking/action pill 与可感知 dwell、Advisor 规则基线与 Solver 模拟估计/分歧原因、Solver 全部尺度、Range Explorer、showdown、next hand、reload/reconnect 与终局私牌清理。真实服务 golden journey 覆盖连续两手与 API/状态闭环；受控 fixture 提供确定性 showdown/dwell 断言。

## 剩余风险与未实测项

- 依赖安全 delivery `1e6dee37e59d9b72f7098939508f4e259dbeb326` 及首轮 UI P1 delivery `82cde45027bb4ac16457ab467afca7dfd0ae894a` 尚待独立窄审；上游 Standards/Spec review 不覆盖这些新 diff。
- 精确 Node 24.15.0 未在本机测量；本机为 24.18.0。GitHub CI 必须复跑 audit、unit、tsc、build 与当前产品 Playwright。
- live PostgreSQL、外部 Redis 未在 follow-up 中测试；本次变更限于 frontend dependency/E2E/provenance。
- 没有人类参与 5 秒任务；这里只报告自动化交互代理。
- 在线 npm/SWC 下载出现明显网络瞬态；本地功能门最终通过，但 CI 的干净安装仍是必要证据。
- Binary/container 实际捆绑、artifact integrity、notice/corresponding-source 处理未闭合。

## Binary/container 边界

`docs/provenance/sbom.json` 的 `bundled_binary_container_release=FAIL`。npm/Python binary artifact integrity 与各平台 Sharp/libvips 实际捆绑、notice、corresponding-source 处理尚未闭合。因此禁止发布捆绑二进制或容器；这与 source license verdict PASS 及本地 audit 0 相互独立。

## 最终解锁条件

1. 独立窄审 `7ccbc2d..1e6dee3` 中的 release-only 增量，确认依赖升级、Range overlay 修复与 E2E 证据无 P0/P1。
2. GitHub CI 在仓库精确 Node 24.15.0 环境完成 clean install、`npm audit --audit-level=high`、完整 unit、tsc、production build 与当前产品 Playwright。
3. 上述两项通过后，Controller 才可把 `source_release_ready` 从 `pending_independent_review_and_ci` 改为最终 PASS。
4. Binary/container 发布继续保持禁止，直到 SBOM 对应 verdict 独立转为 PASS。
