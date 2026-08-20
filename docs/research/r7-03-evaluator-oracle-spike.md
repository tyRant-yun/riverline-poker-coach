# R7-03 Evaluator 与 Oracle 采用结论

状态：2026-08-20 完成；解锁 R7-04/R7-05，不改变生产默认路径。

## 决策

- **Riverline 当前 evaluator：继续作为 MVP 默认后端。** 固定 seed 的 5/6/7-card 差分测试对独立 brute-force oracle 为 0 mismatch，性能足够支撑 Range V2 与 Fast Solver L1.5 首版。
- **PH Evaluator：暂缓生产采用。** Apache-2.0、Python 接入成本低，保留为可选后端候选；只有目标 Python 3.13 环境完成安装/打包、5/6/7-card 零差分、性能和本地许可证元数据门后才可启用。
- **noambrown/poker_solver：延期至 R7-06。** MIT、适合 HU river subgame/oracle，但不匹配当前 multiway、多街实时链路，也不进入 MVP Python 请求路径。
- **OpenSpiel：仅作离线 conformance 候选。** Apache-2.0、适合 Kuhn/Leduc/CFR 正确性回归；Windows 支持和研究框架体量不适合作为在线依赖。
- **R7-04/05 不新增强制第三方 evaluator/solver 依赖。** 直接复用当前 evaluator、PokerKit 规则权威和已有 brute-force oracle。

## 本机实测

基线：`codex/r7-final-mvp`，Python 3.13。

```text
py -3.13 -m pytest backend/tests/test_evaluator_benchmark.py backend/tests/test_fast_solver.py -q
9 passed
```

```text
py -3.13 -m poker_coach.simulator.evaluator_benchmark --samples-per-size 2000 --rounds 3
oracle: 0 mismatch / 6000 samples
current evaluator: 148,411 evaluations/s
p50: 6,745 ns/evaluation
p95: 6,755 ns/evaluation
PH Evaluator candidate: unavailable (not installed)
adoption gate: FAIL, as expected
```

未安装候选依赖、未构建 C++ solver、未运行 OpenSpiel；这些项目的性能、Windows 打包与收敛均为 `measured: false`。

## R7-04/05 冻结边界

- evaluator backend 必须可替换且懒加载；候选缺失时无条件回退当前 evaluator。
- 任何候选必须暴露 `name/version/license/status`，并通过 5/6/7-card differential zero-mismatch gate。
- Range/Solver 只消费公开前缀、Hero 私牌和合法动作；禁止读取对手真实私牌、terminal payout 或未来隐藏事件。
- 摊牌公开牌只用于终局展示/复盘真值，不得回填此前 Hero 所见 belief。
- L1.5 必须保留确定性 decision seed、合法 sizing、置信区间和诚实的 `ready/degraded/unsupported` 状态。
- L2/oracle 结果不得伪装为完整 6-max GTO。

## 一手来源

- [PH Evaluator](https://github.com/HenryRLee/PokerHandEvaluator)
- [noambrown/poker_solver](https://github.com/noambrown/poker_solver)
- [OpenSpiel Windows support](https://github.com/google-deepmind/open_spiel/blob/master/docs/windows.md)

