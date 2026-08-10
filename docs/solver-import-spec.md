# Solver 输出导入规范（solver_backed 数据接入）

版本：draft-1 · 日期：2026-08-10 · 状态：草案（待首个真实数据验证）

本规范定义把**已验证、有来源**的求解器输出导入策略库为 `solver_backed` `StrategyArtifact` 的数据契约、校验规则与管线。它是独立设计，不复制任何 AGPL 项目代码（TexasSolver / postflop-solver 仅作为格式参考来源，见 ADR-0004）。

## 1. 目标与边界

- 目标：让有来源的求解数据（PioSOLVER、TexasSolver 系等导出）进入现有匹配与教学链路，且只在 `exact` 或获批 `compatible` 匹配时允许引用频率（ADR-0003）。
- 边界：不导入求解器代码；不导入无来源/无许可证/无版本的数据；不导入任何声称 GTO 但无 `solver_backed` 来源等级的数据。

## 2. 求解场景输入（与 ScenarioSpec 的映射）

求解器需要与现有 `ScenarioSpec` 一致的最小输入：

| 求解输入 | ScenarioSpec 字段 |
|---|---|
| 牌面 | `board` |
| 双方范围（169 格或组合+权重） | `hero_range` / `villain_range` |
| 有效筹码 | `seats[].starting_stack`（min 两侧） |
| 盲注/ante/rake | `small_blind` / `big_blind` / `ante` / `rake_config`（当前 MVP 无 rake） |
| 下注树 | `allowed_bet_sizes` + `action_history`（决策点 `decision_point`） |

导入时记录求解场景哈希（`scenario_hash` 同算法），保证数据可追溯。

## 3. 输出数据契约（本规范定义的规范 JSON）

每个求解结果包含元数据 + 动作树：

```jsonc
{
  "schemaVersion": 1,
  "solver": {"name": "texasholdemsolverjava", "version": "0.1.0", "license": "MIT"},
  "source": {"creator": "...", "validatedBy": "cfr_iterations_1000", "trustLevel": "verified"},
  "game": {"variant": "nlhe", "board": ["Qs","Jh","2h"], "effectiveStack": 200, "rakeSignature": "none"},
  "betTree": [
    {"action": "call", "amountTo": 50},
    {"action": "bet", "amountTo": 100}
  ],
  "rootNode": {
    "street": "flop",
    "actorSeat": 1,
    "pot": 100,
    "actions": ["check", "bet_50", "all_in"],
    "strategy": {
      "AhKh": {"check": {"frequency": 0.42}, "bet_50": {"frequency": 0.51, "ev": 3.2}, "all_in": {"frequency": 0.07}},
      "2c2d": {"check": {"frequency": 1.0}}
    },
    "children": {
      "bet_50": {
        "street": "flop", "actorSeat": 0, "pot": 200,
        "actions": ["call", "fold", "raise_60"],
        "strategy": {"AhKh": {"call": {"frequency": 0.8}, "fold": {"frequency": 0.2}}}
      }
    }
  }
}
```

- `strategy` 键为具体两张底牌（如 `AhKh`）；`frequency` 是 0..1 的权重，每手牌各动作频率之和为 1；`ev` 以筹码为单位（可选）。
- 节点动作命名与求解器导出一致，导入适配器负责映射到领域动作（`check`/`call`/`bet`/`raise_to`/`fold`/`all_in`）与金额。
- 树深度不设硬上限，但导入时按 `allowed_bet_sizes` 与合法动作校验每个节点。

## 4. 校验规则（导入前强制）

1. **来源完备**：`solver.license`、`source.creator`、`solver.version` 必填；许可证必须允许本项目使用（AGPL 数据文件本身可用，但需记录来源与许可；AGPL **代码**一律不得引入）。
2. **输入一致**：求解输入（牌面/范围/筹码/下注树）必须与待绑定场景匹配；导入适配器重放 `action_history` 得到每个节点的合法动作集合。
3. **动作合法性**：节点 `actions` 与策略键必须 ∈ 该节点合法动作（复用 `PokerKitAdapter` 重放的 `legal_actions`）；非法动作直接拒绝该条目。
4. **频率一致性**：每手牌频率之和 ∈ [0.999, 1.001]；负频率/负 EV 拒绝。
5. **手牌合法性**：策略键必须为两张不同牌；与已知牌（board/双方范围）重叠的组合拒绝（dead-card 过滤）。
6. **定量依据**：任何含频率/EV 的条目必须带 `quantitativeBasis`（求解器+版本+迭代/精度），否则不满足 `StrategyArtifact` 校验（`strategy/models.py` 已强制）。

## 5. 导入管线

```text
求解器导出文件（PioSOLVER / TexasSolver 系 JSON 等）
  → 适配器映射为本规范 JSON（独立实现，仅消费数据文件）
  → 校验器（第 4 节全部规则）
  → StrategyArtifact（source_level=solver_backed，含 quantitative_basis / license / version）
  → store.register_strategy_artifacts()（已有）
  → StrategyCatalog 匹配：exact / compatible / approximate / no_match
  → 教学层仅在 can_quote_frequencies=True 时输出频率/EV（ADR-0003）
```

## 6. 参考格式映射说明（只读研究结论）

- TexasSolver 系导出为动作树嵌套 JSON：节点含 `actions`（动作字符串）、`player`、`childrens`（按动作嵌套）、`strategy`（按手牌的动作频率/EV 表）。适配器把这些节点展平/映射为第 3 节的规范树。
- 求解输入格式（`set_range_ip|oop AA,AK:0.75,...`、`set_bet_sizes`）可与 `RangeSpec.matrix_169` / `allowed_bet_sizes` 互转；`:0.75` 权重直接映射为 `Weight`。

## 7. 拒绝清单（反例）

- 来源不明的"策略表"、贴吧/论坛截图数据；
- 无法重放求解输入的树（与合法动作矛盾）；
- 未记录求解器版本与验证方式的频率数据；
- 声称 GTO 但来源等级非 `solver_backed` 的条目。
