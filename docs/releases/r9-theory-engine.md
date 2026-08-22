# R9 Theory Engine source MVP 发布门

日期：2026-08-22  
分支：`codex/r9-07-release`  
冻结发布候选：`f000deaf001f493909fc6e9192f54096bb1b5bc0`

## 结论

- `source_repository_release: PASS`（本地 source license/provenance verdict）。
- `local_release_gate: PASS`：最终候选的 Playwright、SQLite/noRedis 产品 smoke、license/provenance 与 npm audit 已实测通过；生产代码未在最终 E2E 文案修订后变化。
- `binary_or_container_release_ready: NOT READY`：SBOM 的 bundled binary/container verdict 为 `FAIL`。
- 本文不代替 Controller 的独立最终审计、远端 CI、推送或 main 合并决定。

## 理论能力与诚实边界

默认 provider release gate 实测 13 个点全部通过：5 个 6-max RFI、5 个 vs-RFI、1 个 HU river root、1 个 C fallback、1 个 typed unsupported。开发机的各点 P50/P95 均低于 250ms 阈值；其中 HU river root P50/P95 为 6.8742/7.19114ms。它们是本机 provider 测量，不是产品 SLA。

当前可声明的覆盖范围是：B 级的已覆盖 preflop artifact，及受限的 HU river jam L2；C/unsupported 场景只给出诚实的 fallback，不伪造策略频率、EV、尺度或推荐动作。它不是完整 6-max GTO/Nash solver。

## 质量门证据

| 范围 | 实测 commit | 原始命令 | 结果 |
|---|---|---|---|
| Backend 完整门 | `12c3dba66f2bade339f3a5cadadc5c189962f3da` | `cd backend; py -3.13 -m pytest -q --junitxml=<temp>` | 696 tests，0 failures、0 errors、10 skipped，81.014s。最终 `f000dea` 仅含两个 E2E 文案断言与 handoff，不含生产代码。 |
| Python 编译/依赖 | `12c3dba` | `py -3.13 -m compileall -q poker_coach`; `py -3.13 -m pip check` | 均 exit 0；`No broken requirements found.` |
| Provider benchmark | `12c3dba` | `cd backend; py -3.13 -m poker_coach.theory` | 13/13 gate passed；本机 P50/P95 证据见上。 |
| Fixture corpus | `12c3dba` | `cd backend; py -3.13 -m poker_coach.theory --verify-corpus` | intentional green/red corpus expectations met。 |
| Frontend clean install | `12c3dba` | `cd frontend; npm ci` | 180 packages audited，0 vulnerabilities；本机 Node 24.18.0 与 declared 24.15.0 不同。 |
| Frontend unit / TypeScript / build | `12c3dba` | `npm test`; `npm run lint`; `npm run build` | 32 files / 178 tests passed；`tsc --noEmit` exit 0；production build exit 0。 |
| Final Playwright | `f000deaf001f493909fc6e9192f54096bb1b5bc0` | `cd frontend; npm run test:e2e` | 7/7 passed；webServer 同时验证 API `/health` 与 Web 启动可达。 |
| SQLite/noRedis product smoke | `f000dea` | `cd backend; py -3.13 -m pytest -q tests/test_continuous_table_api.py::test_three_hands_reconnect_idempotency_and_information_isolation tests/test_continuous_table_api.py::test_profiles_conflicts_and_bot_fallback_are_stable tests/test_continuous_table_api.py::test_completed_table_materializes_one_safe_review_and_reconnects tests/test_session_stats_projection.py::test_session_stats_accumulate_exact_preflop_rates_and_sparse_participants tests/test_theory_recommendation.py` | 15 passed：三手/reconnect、Theory Bot fallback、review、SQLite stats、Theory/Range/Explainer、HU river jam L2 B 与不安全树 C fallback。 |
| Source license/provenance | `f000dea` | `py -3.13 -m pytest -q backend/tests/test_license_provenance.py`; `py -3.13 tools/generate_license_provenance.py --check` | 6 passed；generator PASS；SBOM source verdict PASS。 |
| npm production audit | `f000dea` | `cd frontend; npm audit --omit=dev --audit-level=high` | `found 0 vulnerabilities`。 |

## 发布限制

`docs/provenance/sbom.json` 明确给出：`source_repository_release=PASS`，但 `bundled_binary_container_release=FAIL`。失败原因包括 Python artifact integrity 未锁定，以及 Sharp/libvips 实际捆绑二进制、notices 和 corresponding-source handling 尚未完成。因此只可评估 source repository release；禁止发布捆绑二进制或容器。

Next 的运行副作用只生成本地 `frontend/next-env.d.ts`、`frontend/AGENTS.md`、`frontend/CLAUDE.md`，均未纳入本次提交。

## 后续 Controller 门

1. 对 `1dac59f..f000dea` 进行最终独立窄审，只报告 P0/P1。
2. 在远端精确 Node 24.15.0 的干净环境复跑 CI。
3. 仅当上述门通过后，再决定推送、PR 和 main 合并；binary/container 仍保持 NOT READY。
