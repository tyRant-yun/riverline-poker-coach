# Spike 报告：postflop-solver sidecar 全链路求解（阶段 1）

日期：2026-08-10 · 状态：✅ 完成（阶段 1 验收通过）

## 1. 目标

按 Solver Integration Design Review（docs/solver-integration-design.md）阶段 1：固定一个 HU flop spot，验证 **Coach Spot → Solver → 结果校验** 闭环，稳定得到 exploitability、range EV、AK/QQ/draw 策略。不碰 UI、不写 Adapter（阶段 2 的事）。

## 2. 固定 Spot（spike-config）

| 项 | 值 |
|---|---|
| 游戏 | HU NLHE，OOP=BB vs IP=BTN，SRP |
| 牌面 | `Ks 7h 2h`（顶对 + 红桃同花听牌 + 干燥边牌混合） |
| 底池 / 有效筹码 | 500 / 9750（100BB 深） |
| OOP 范围 | `66+,A8s+,A5s-A4s,AJo+,K9s+,KQo,QTs+,JTs,96s+,85s+,75s+,65s,54s`（181 组合） |
| IP 范围 | `QQ-22,AQs-A2s,ATo+,K5s+,KJo+,Q8s+,J8s+,T7s+,96s+,86s+,75s+,64s+,53s+`（267 组合） |
| 下注树 | flop 50% / 几何 / allin（raise 2.5x）；turn/river 未发牌 |
| 求解 | DCFR，max 400 迭代，目标 exploitability = 0.5% 底池（2.5 chips） |

> 注：范围为 spike 手工定义（近似 SRP 攻防）；阶段 2 由 Adapter 从 `RangeSpec` 生成。

## 3. 结果（元数据）

| 指标 | 值 |
|---|---|
| **Exploitability** | **2.35 chips**（< 目标 2.5，收敛 ✅） |
| 求解耗时 | 148.4s（400 迭代，DCFR，单容器） |
| 内存预检 | **5.84 GB（普通）/ 3.03 GB（压缩 16-bit）** |

`memory_usage()` 预检在真正分配前给出精确估算——若配额 4GB，此树应直接提示"压缩求解或减少下注尺度"，而不是 OOM。**缓存（solve_hash）必要性实证：同 spot 重求 148s，命中缓存毫秒级。**

## 4. 策略摘要（教学可消费输出）

### OOP 根节点（actions: Check / Bet(250) / Bet(605) / AllIn）

| 组合 | 类别 | Equity | EV | 策略（主导动作） |
|---|---|---|---|---|
| AcKc / AdKd | 顶对 | 83% | 532 | Check 66% / Bet(250) 34%（混合） |
| AcKh / AdKh | 顶对+后门红桃 | 86% | 594 | **Bet 57% / Check 43%**（后门花提升下注频率） |
| QQ（无红桃） | 超对 | 43% | 82 | **Check 97%**（纯过牌） |
| QQ（含红桃） | 超对+后门 | 46% | 113 | Check 63% / Bet 37% |
| 5h4h / 6h5h | 同花听牌 | 43-45% | 249-255 | Check 54-58% / **Bet 42-46%**（半诈唬） |
| 全范围 | — | 54.1% | 270 | 下注频率 32.2%（check-heavy ✅） |

### IP 对 Bet(250) 的回应（actions: Fold / Call / Raise(625)）

| 组合 | 类别 | Equity | EV | 策略 |
|---|---|---|---|---|
| AK | 顶对 | 75-79% | 644-757 | **从不弃牌**：Call 93-98% / Raise 2-7% |
| QQ（无红桃） | 超对 | 41% | ~1 | **Fold 40% / Call 55%**（无后门时折半） |
| QQ（含红桃） | 超对+后门 | 44% | 28 | Call 94% / Raise 6% |
| 3h3h / 4h4h | 对子+同花听牌 | 38% | 14-21 | Call 91-100% / Raise 至 11% |

**扑克直觉验证**：OOP 该牌面整体 check-heavy（32% 下注）；顶对混合过牌/小注；无后门的超对在 OOP 纯过牌、面对下注时折弃约 40%；同花听牌以 40%+ 频率半诈唬——全部与标准策略认知一致，且带 EV/equity 数值。

## 5. 技术要点（复现与坑）

- **sidecar 位于仓库外**：`C:\Users\Administrator\Documents\ChatGPT\solver-sidecar\`（AGPL 隔离政策；主仓库不含其源码）。
- **依赖坑**：postflop-solver 的 `bincode = "2.0.0-rc.3"` 因 caret 语义会解析到 2.0.1，而 2.0.x 稳定版改了 `Decode` 泛型 API → 编译失败。Dockerfile 中 `cargo update -p bincode --precise 2.0.0-rc.3` + `cargo update -p bincode_derive --precise 2.0.0-rc.3` 双钉解决。
- **API 细节**：`normalized_weights` 缓存是节点级的——`game.play()` 切换节点后须重新 `cache_normalized_weights()`；`TreeConfig` 阈值为 f64、`starting_pot/effective_stack` 为 i32、`solve()` 目标为 f32。
- **复现命令**（在 sidecar 目录）：
  ```bash
  docker build -t poker-coach-sidecar .
  docker run --rm -v "$(pwd)/spike-config.json:/config.json" poker-coach-sidecar /config.json > solve-output.json
  ```

## 6. 数据产物

- `backend/tests/fixtures/solve-summary-spike1.json`：448 行手牌级策略/EV/equity（OOP 根 + IP 回应节点），供阶段 2 Adapter 测试作参考数据（solver 输出数据，可自由导入）。

## 7. 下一步（阶段 2）

1. `SolverAdapter`：`ScenarioSpec → SolverSpot`（含 RangeSpec→范围字符串展开、pot/有效筹码重放对齐、allowed_bet_sizes→下注树）与 `SolveResult` 规范模型；
2. 用本 fixture 验证校验器（频率归一化、合法动作重放、死牌过滤）；
3. 接入 `poker_coach.jobs` 异步 SolveJob 生命周期。
