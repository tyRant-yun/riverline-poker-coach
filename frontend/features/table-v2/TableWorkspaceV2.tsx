"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { formatCard } from "../../lib/poker/cards";
import { RANKS, matrixCell } from "../../lib/poker/matrix";
import type { ContinuousTable, TableInsightsResponse, TableReconciliationResponse, TableReviewResponse, TableSolverResponse } from "../../types/api";
import "../../styles/table-v2.css";

export type SeatStatus = "current" | "folded" | "all-in" | "showdown" | "dealer" | "waiting";
export type TableSeat = { id: string; name: string; stack: string; position: string; status: SeatStatus; cards?: string[] };
export type ActionDelta = { id: string; actor: string; actorSeat?: string; label: string; kind: "action" | "raise" | "all-in" | "showdown"; potDelta?: string };
export type PlaybackSpeed = "comfort" | "fast" | "instant" | "skip" | "slow" | "standard";
export type Scheduler = { setTimeout: (fn: () => void, ms: number) => number; clearTimeout: (id: number | undefined) => void };

const playbackTiming: Record<Exclude<PlaybackSpeed, "skip">, { think: number; readable: number; transition: number }> = {
  comfort: { think: 450, readable: 750, transition: 150 }, standard: { think: 450, readable: 750, transition: 150 }, slow: { think: 600, readable: 900, transition: 200 }, fast: { think: 220, readable: 400, transition: 90 }, instant: { think: 0, readable: 0, transition: 0 },
};
const actionNames: Record<string, string> = { fold: "弃牌", check: "过牌", call: "跟注", bet: "下注", raise: "加注", raise_to: "加注", all_in: "全压" };

export class ActionPlaybackQueue {
  private timer: number | undefined;
  private token = 0;
  constructor(private readonly scheduler: Scheduler, private readonly reducedMotion = false) {}
  play(actions: readonly ActionDelta[], speed: PlaybackSpeed, onAction: (action: ActionDelta) => void, onComplete?: () => void, onThinking?: (action?: ActionDelta) => void) {
    this.cancel();
    const token = ++this.token;
    if (speed === "skip" || speed === "instant") { actions.forEach(onAction); onThinking?.(); onComplete?.(); return; }
    if (this.reducedMotion) {
      let index = 0;
      const next = () => {
        if (token !== this.token) return;
        const action = actions[index++];
        if (!action) { onThinking?.(); onComplete?.(); return; }
        onAction(action); onThinking?.();
        this.timer = this.scheduler.setTimeout(next, 750);
      };
      next();
      return;
    }
    let index = 0;
    const next = () => {
      if (token !== this.token) return;
      const action = actions[index++];
      if (!action) { onThinking?.(); onComplete?.(); return; }
      const timing = playbackTiming[speed];
      onThinking?.(action);
      this.timer = this.scheduler.setTimeout(() => {
        if (token !== this.token) return;
        onAction(action); onThinking?.();
        this.timer = this.scheduler.setTimeout(next, timing.readable + timing.transition);
      }, timing.think);
    };
    next();
  }
  cancel() { this.token++; if (this.timer !== undefined) this.scheduler.clearTimeout(this.timer); this.timer = undefined; }
}

export function ActionPlaybackController({ actions, identity, speed, reducedMotion, scheduler, onChange, onThinking, onComplete }: {
  actions: readonly ActionDelta[]; identity: string; speed: PlaybackSpeed; reducedMotion: boolean; scheduler?: Scheduler;
  onChange: (action?: ActionDelta) => void; onThinking: (action?: ActionDelta) => void; onComplete: () => void;
}) {
  const queue = useRef<ActionPlaybackQueue | null>(null);
  const callbacks = useRef({ onChange, onThinking, onComplete });
  callbacks.current = { onChange, onThinking, onComplete };
  useEffect(() => {
    queue.current = new ActionPlaybackQueue(scheduler ?? window, reducedMotion);
    if (!actions.length) { callbacks.current.onThinking(undefined); callbacks.current.onChange(undefined); callbacks.current.onComplete(); return () => queue.current?.cancel(); }
    const play = (mode: PlaybackSpeed) => queue.current?.play(actions, mode, (action) => callbacks.current.onChange(action), () => callbacks.current.onComplete(), (action) => callbacks.current.onThinking(action));
    play(speed);
    const onVisibilityChange = () => { if (document.hidden) play("instant"); };
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => { document.removeEventListener("visibilitychange", onVisibilityChange); queue.current?.cancel(); };
  }, [actions, identity, speed, reducedMotion, scheduler]);
  return null;
}

const defaultSeats: TableSeat[] = [
  { id: "0", name: "Hero", stack: "筹码 10,000", position: "BTN", status: "current", cards: ["A♠", "J♠"] },
  ...Array.from({ length: 5 }, (_, index) => ({ id: String(index + 1), name: `Bot ${index + 1}`, stack: "筹码 10,000", position: ["SB", "BB", "UTG", "MP", "CO"][index], status: "waiting" as const })),
];

function seatViews(table?: ContinuousTable): TableSeat[] {
  if (!table) return defaultSeats;
  return table.seats.map((seat) => ({
    id: String(seat.seatId), name: seat.seatId === table.heroSeat ? "Hero" : `Bot ${seat.seatId + 1}`,
    stack: `筹码 ${seat.stack.toLocaleString("zh-CN")}`,
    position: seat.seatId === table.buttonSeat ? "BTN" : ["SB", "BB", "UTG", "MP", "CO", "HJ"][seat.seatId] ?? `Seat ${seat.seatId}`,
    status: seat.status === "folded" ? "folded" : table.handComplete ? "showdown" : seat.seatId === table.currentActor ? "current" : "waiting",
    cards: seat.seatId === table.heroSeat ? table.heroHoleCards.map(formatCard) : seat.revealedHoleCards?.map(formatCard),
  }));
}

export function PokerTableStageV2({ seats = defaultSeats, currentAction, thinkingAction, board = ["Q♠", "J♥", "4♣"], pot = "1,240" }: { seats?: TableSeat[]; currentAction?: ActionDelta; thinkingAction?: ActionDelta; board?: string[]; pot?: string }) {
  return <section className="tv2-stage" aria-label="六人德州扑克牌桌">
    <div className="tv2-felt" />
    <div className="tv2-safe-zone" aria-label="底池与公共牌安全区"><div className="tv2-pot">底池 <strong>{pot}</strong></div><div className="tv2-board" aria-label="公共牌">{board.length ? board.map((card, index) => <i key={`${card}-${index}`}>{card}</i>) : <span>等待公共牌</span>}</div></div>
    {seats.map((seat, index) => { const thinking = thinkingAction?.actorSeat === seat.id; const acted = currentAction?.actorSeat === seat.id; return <article className={`tv2-seat tv2-seat-${index} ${seat.name === "Hero" ? "tv2-hero-seat" : ""} is-${seat.status} ${thinking ? "is-thinking" : ""}`} data-seat={seat.id} key={seat.id} aria-label={`${seat.position} ${seat.name} ${thinking ? "思考中" : seat.status}`}><span className="tv2-position">{seat.position}</span><div className="tv2-avatar">{seat.name.slice(0, 1)}</div><div className="tv2-player"><b>{seat.name}</b><small>{seat.stack}</small></div>{thinking && <span className="tv2-seat-narrative" data-testid="bot-thinking">{seat.name} 思考中…</span>}{acted && <span className="tv2-seat-narrative tv2-action-pill" data-testid="bot-action-bubble" aria-live="polite">{currentAction.label}{currentAction.potDelta ? ` ${currentAction.potDelta}` : ""}</span>}{seat.cards?.length ? <div className="tv2-holecards" aria-label="Hero 手牌">{seat.cards.map((card, cardIndex) => <i key={`${card}-${cardIndex}`} aria-label={card}>{card}</i>)}</div> : null}{seat.status === "folded" && <span className="tv2-fold">弃牌</span>}</article>; })}
  </section>;
}

export function HeroActionDockV2({ table, disabled = false, amounts = {}, onAmountChange, onAction, onNextHand, review, advisor }: {
  table?: ContinuousTable; disabled?: boolean; amounts?: Record<string, string>; onAmountChange?: (action: string, amount: string) => void;
  onAction?: (action: ContinuousTable["heroLegalActions"][number]) => void; onNextHand?: () => void; review?: TableReviewResponse["review"] | null; advisor?: TableInsightsResponse["insights"]["advisor"];
}) {
  const legalActions = table?.heroLegalActions ?? [];
  useEffect(() => {
    const keydown = (event: KeyboardEvent) => {
      if (disabled || event.defaultPrevented || (event.target instanceof HTMLInputElement)) return;
      const action = ({ f: "fold", c: "call", r: "raise" } as Record<string, string | undefined>)[event.key.toLowerCase()];
      const legal = legalActions.find((item) => item.action === action);
      if (legal) { event.preventDefault(); onAction?.(legal); }
    };
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, [disabled, legalActions, onAction]);
  const advisorText = advisor?.available ? `建议：${actionNames[advisor.result?.recommendedAction?.action ?? ""] ?? advisor.result?.recommendedAction?.action ?? "暂未给出行动"}` : advisor?.unavailableReason ?? "Advisor 暂不可用；请以合法行动与桌面事实为准。";
  if (table?.handComplete) return <section className="tv2-dock" aria-label="Hero 操作区"><div className="tv2-advisor-summary" aria-label="Advisor 摘要">{advisorText}</div><div><small>本手已结算</small><strong data-testid="table-review-status">{review ? `复盘可用：${review.heroDecisions.length} 个 Hero 决策` : "复盘未就绪"}</strong></div><button className="primary" disabled={disabled} onClick={onNextHand} data-testid="next-hand">下一手</button></section>;
  return <section className="tv2-dock" aria-label="Hero 操作区" aria-busy={disabled}><div className="tv2-advisor-summary" aria-label="Advisor 摘要">{advisorText}</div><div><small>{disabled ? "Bot 行动播放中" : "轮到你 · 按 F / C / R 快捷操作"}</small><strong>{table ? `Hero · ${table.heroHoleCards.map(formatCard).join(" ")}` : "Hero"}</strong></div><div className="tv2-actions" data-testid="hero-legal-actions">{legalActions.map((legal) => <div key={legal.action}>{legal.minAmount != null && <input aria-label={`${legal.action} amount`} type="number" min={legal.minAmount} max={legal.maxAmount} value={amounts[legal.action] ?? String(legal.minAmount)} disabled={disabled} onChange={(event) => onAmountChange?.(legal.action, event.target.value)} />}<button aria-label={actionNames[legal.action] ?? legal.action} disabled={disabled} onClick={() => onAction?.(legal)} data-testid={`hero-action-${legal.action}`}>{actionNames[legal.action] ?? legal.action}{legal.minAmount != null ? ` ${legal.minAmount}-${legal.maxAmount}` : ""} {legal.action === "fold" ? <kbd>F</kbd> : legal.action === "call" ? <kbd>C</kbd> : legal.action === "raise" ? <kbd>R</kbd> : null}</button></div>)}</div></section>;
}

function rangeMessage(reason?: string) {
  if (reason === "stack_bucket_unsupported") return "当前筹码档位暂无可用 Range 估计。";
  if (reason === "private_event_forbidden") return "当前事件不是公开行动前缀，无法安全估计范围。";
  return reason ? `当前暂无 Range 数据：${reason.replaceAll("_", " ")}` : "当前未返回座位 Range Belief。";
}
function approximationLabel(reason?: string | null) {
  const match = reason?.match(/^nearest_stack_bucket:(.+)$/);
  return match ? `近似：${match[1].toUpperCase()} 最近档` : "近似估计";
}
function percent(value?: string | number | null) {
  return value == null ? "—" : `${(Number(value) * 100).toFixed(1)}%`;
}
function chips(value?: string | number | null) { return value == null || !Number.isFinite(Number(value)) ? "—" : Math.round(Number(value)).toLocaleString("zh-CN"); }
function ev(value?: string | number | null) { return value == null || !Number.isFinite(Number(value)) ? "—" : `${Number(value) >= 0 ? "+" : ""}${Number(value).toFixed(1)}`; }
function candidateLabel(candidate: { action: string; amount?: number | null; amountChips?: number | null; potPercentage?: string | null; potPct?: string | null }) {
  const potPct = candidate.potPercentage ?? candidate.potPct;
  const amount = candidate.amountChips ?? candidate.amount;
  const sizing = amount != null ? (potPct != null ? ` · ${Number(potPct).toFixed(1)}% pot · ${chips(amount)}` : ` ${chips(amount)}`) : "";
  if (candidate.action === "all_in") return `全压${sizing}`;
  const label = actionNames[candidate.action] ?? candidate.action;
  return `${label}${sizing}`;
}
const reasonLabels: Record<string, string> = {
  advisor_degraded: "规则基线降级", solver_degraded: "模拟估计降级", solver_unavailable: "模拟估计不可用",
  sizing_set_mismatch: "尺度集合不同", range_missing: "Range 不可用", range_coarse: "Range 较粗",
  model_limitations: "模型限制", solver_sizing_close: "尺度接近", solver_sizing_robust: "尺度稳健",
  extreme_sizing_not_robust: "极端尺度不稳健", solver_uncertainty_unavailable: "不确定性不可用", unexplained: "尚无可验证原因",
};
function reconciliationText(reconciliation?: TableReconciliationResponse["reconciliation"] | null) {
  if (!reconciliation) return "等待同一决策节点的对照结果";
  const kind = ({ exact_action: "动作与尺度一致", same_action_different_sizing: "动作一致、尺度不同", different_action: "存在分歧", insufficient_evidence: "暂不可比较" })[reconciliation.agreement.kind];
  const reasons = reconciliation.agreement.reasonCodes.map((code) => reasonLabels[code] ?? code).join(" · ");
  return `${kind}${reasons ? ` · ${reasons}` : ""}`;
}
function candidateDelta(candidate: NonNullable<TableSolverResponse["solver"]>["candidates"][number], candidates: NonNullable<TableSolverResponse["solver"]>["candidates"]) {
  if (candidate.deltaEvChips != null && Number.isFinite(Number(candidate.deltaEvChips))) return Number(candidate.deltaEvChips);
  const best = Math.max(...candidates.map((item) => Number(item.approximateEvChips)).filter(Number.isFinite));
  return Number.isFinite(best) ? Number(candidate.approximateEvChips) - best : Number.NEGATIVE_INFINITY;
}
type RangeBelief = NonNullable<TableInsightsResponse["insights"]["seatBeliefs"]>[number];
type RangeFilter = "all" | "pair" | "suited" | "offsuit" | "top" | "up" | "down" | "blocked";
function rangeEvidence(source?: string) { return `${source?.includes("heuristic") || !source ? "C 级 · 公开行动启发式" : "C 级 · 公开数据估计"}（非 A/B 策略）`; }
function rangeCoverage(belief: RangeBelief) { return belief.approximate ? `覆盖：近似 · ${approximationLabel(belief.approximationReason)}` : "覆盖：当前 DTO 未提供适用树/筹码/抽水范围"; }
function rangeChange(reason?: string) { if (!reason) return "当前节点为初始先验"; if (reason.includes("公开行动")) return reason; return "公开行动后范围已更新"; }
function rangeNumber(value?: string | number | null, digits = 1) { const number = Number(value); return Number.isFinite(number) ? number.toLocaleString("zh-CN", { maximumFractionDigits: digits, minimumFractionDigits: digits }) : "—"; }
function handKind(hand: string) { return hand.length === 2 ? "pair" : hand.endsWith("s") ? "suited" : "offsuit"; }
function cellDelta(current: RangeBelief, previous: RangeBelief | undefined, hand: string) {
  if (!previous?.matrix169 || !current.matrix169) return null;
  return Number(current.matrix169[hand]?.probabilityMass ?? 0) - Number(previous.matrix169[hand]?.probabilityMass ?? 0);
}
function densityLevel(mass: number) { return Math.max(0, Math.min(6, Math.round(Math.max(0, mass) * 60))); }
function RangeExplorer({ belief, previous, baselineAvailable, onClose }: { belief: RangeBelief; previous?: RangeBelief; baselineAvailable: boolean; onClose: () => void }) {
  const [mode, setMode] = useState<"weight" | "delta">("weight");
  const [filter, setFilter] = useState<RangeFilter>("all");
  const matrix = belief.matrix169;
  if (!matrix) return <section className="tv2-range-explorer" role="dialog" aria-label="Range Explorer"><button onClick={onClose}>关闭</button><p>当前座位没有可展开的 169 格范围。</p></section>;
  const cells = RANKS.flatMap((_, row) => RANKS.map((__, column) => {
    const hand = matrixCell(row, column); const item = matrix[hand]; const mass = Number(item?.probabilityMass ?? 0); const delta = cellDelta(belief, previous, hand); const blocked = item != null && item.comboCount === 0;
    const kind = handKind(hand); const visible = filter === "all" || (filter === "top" && mass > 0) || (filter === "blocked" && blocked) || (filter === kind) || (filter === "up" && (delta ?? 0) > 0) || (filter === "down" && (delta ?? 0) < 0);
    const detail = `${hand}；权重 ${rangeNumber(mass * 100, 2)}%；可用组合 ${item?.comboCount ?? "未知"}${delta == null ? "；变化基线不可用" : `；变化 ${delta >= 0 ? "+" : ""}${rangeNumber(delta * 100, 2)}%`}${blocked ? "；已阻断" : ""}`;
    const deltaKind = delta == null ? "unavailable" : delta > 0 ? "up" : delta < 0 ? "down" : "flat";
    return <button type="button" key={hand} aria-label={detail} className={`tv2-range-cell density-${densityLevel(mass)} delta-${deltaKind} ${visible ? "" : "is-filtered"} ${blocked ? "is-blocked" : ""} ${belief.confidence === "low" ? "is-low-confidence" : ""}`} data-kind={kind} data-testid={`range-cell-${hand}`} title={detail}><span>{hand}</span>{mode === "delta" && delta != null && <em>{delta > 0 ? "↑" : delta < 0 ? "↓" : "—"}</em>}{blocked && <i aria-hidden="true">×</i>}</button>;
  }));
  return <section className="tv2-range-explorer" role="dialog" aria-modal="true" aria-label="Range Explorer">
    <header><div><h2>Range Explorer · 座位 {belief.seatId + 1}</h2><p>对角线：对子 · 右上：同花 · 左下：非同花</p></div><button onClick={onClose}>关闭矩阵</button></header>
    <div className="tv2-range-controls"><fieldset><legend>显示</legend><button aria-pressed={mode === "weight"} onClick={() => setMode("weight")}>当前权重</button><button aria-pressed={mode === "delta"} onClick={() => setMode("delta")}>相对上一公开行动</button></fieldset><fieldset><legend>筛选</legend>{(["all", "pair", "suited", "offsuit", "top", "up", "down", "blocked"] as RangeFilter[]).map((item) => <button key={item} aria-pressed={filter === item} onClick={() => setFilter(item)}>{({ all: "全部", pair: "对子", suited: "同花", offsuit: "非同花", top: "Top", up: "增加", down: "减少", blocked: "Blocked" })[item]}</button>)}</fieldset></div>
    {mode === "delta" && !baselineAvailable && <p className="tv2-range-unavailable">变化基线不可用：需同一 session、hand 与座位的上一份已接受结果。</p>}
    <div className={`tv2-range-grid mode-${mode}`} aria-label={`座位 ${belief.seatId + 1} Range 矩阵`}>{cells}</div>
    <footer className="tv2-range-legend"><span><b className="density-0" /> 权重 0–1.7%</span><span><b className="density-3" /> 中等 3.4–6.7%</span><span><b className="density-6" /> 高 ≥8.4%</span><span><b className="delta down" /> 变化：负↓ 减少</span><span><b className="delta flat" /> 零— 不变</span><span><b className="delta up" /> 正↑ 增加</span><span><b className="blocked" /> × 已阻断</span><span><b className="low" /> 斜纹：低置信度</span></footer>
    <p className="tv2-range-unavailable">构成分析尚不可用：当前 DTO 未提供 postflop 手牌、听牌或 equity buckets。</p>
  </section>;
}
function statText(stats: NonNullable<TableInsightsResponse["insights"]["stats"]>) {
  return stats.bySeat.map((stat) => `座位 ${stat.seatId + 1}：入池率 ${(stat.vpip * 100).toFixed(0)}% · 翻前加注率 ${(stat.pfr * 100).toFixed(0)}% · 3Bet ${(stat.threeBet * 100).toFixed(0)}%`).join("；");
}

export function InsightRailV2({ insights, solver, reconciliation, table, solverLoading = false, solverElapsedMs }: { insights?: TableInsightsResponse["insights"] | null; solver?: TableSolverResponse["solver"] | null; reconciliation?: TableReconciliationResponse["reconciliation"] | null; table?: ContinuousTable; solverLoading?: boolean; solverElapsedMs?: number | null }) {
  const [rangeSeatId, setRangeSeatId] = useState<number | null>(null);
  const [explorerOpen, setExplorerOpen] = useState(false);
  const [showAllSizes, setShowAllSizes] = useState(false);
  const [rangeSnapshots, setRangeSnapshots] = useState<{ current?: { identity: string; handIdentity: string; beliefs: RangeBelief[] }; previous?: { identity: string; handIdentity: string; beliefs: RangeBelief[] } }>({});
  const rangeIdentity = table ? `${table.sessionId}:${table.handId ?? "none"}:${table.fingerprint}` : "none";
  const rangeHandIdentity = table ? `${table.sessionId}|${table.handId ?? "none"}` : "none";
  const range = insights?.seatBeliefs ?? [];
  const selectedRange = range.find((belief) => belief.seatId === rangeSeatId) ?? range.find((belief) => belief.available) ?? range[0];
  const selectedPosition = selectedRange && table?.seats ? seatViews(table).find((seat) => seat.id === String(selectedRange.seatId))?.position : undefined;
  const baseline = rangeSnapshots.current?.identity === rangeIdentity && rangeSnapshots.current.handIdentity === rangeHandIdentity ? rangeSnapshots.previous?.beliefs?.find((item) => item.seatId === selectedRange?.seatId) : undefined;
  useEffect(() => { setRangeSeatId(null); setExplorerOpen(false); setShowAllSizes(false); }, [rangeIdentity]);
  useEffect(() => { const beliefs = insights?.seatBeliefs; if (beliefs?.length) setRangeSnapshots((existing) => existing.current?.identity === rangeIdentity ? existing : { current: { identity: rangeIdentity, handIdentity: rangeHandIdentity, beliefs }, previous: existing.current?.handIdentity === rangeHandIdentity ? existing.current : undefined }); }, [insights, rangeHandIdentity, rangeIdentity]);
  const movers = selectedRange?.matrix169 && baseline?.matrix169 ? Object.keys(selectedRange.matrix169).map((hand) => ({ hand, delta: cellDelta(selectedRange, baseline, hand) ?? 0 })).filter((item) => item.delta !== 0).sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta)).slice(0, 5) : [];
  const rangeContent = range.length ? <><div className="tv2-range-seats" aria-label="Range 座位选择">{range.map((belief) => <button key={belief.seatId} aria-pressed={selectedRange?.seatId === belief.seatId} onClick={() => { setRangeSeatId(belief.seatId); setExplorerOpen(false); }}>座位 {belief.seatId + 1}</button>)}</div>{selectedRange?.available ? <><p>当前对象：座位 {selectedRange.seatId + 1}{selectedPosition ? ` · ${selectedPosition}` : ""} · {table?.street ?? "街道未提供"}</p><p><strong>范围宽度 {rangeNumber(selectedRange.rangeWidthPct)}%</strong> · 约 {rangeNumber(selectedRange.rangeWidthCombos, 0)} weighted combos</p><p>置信度 {selectedRange.confidenceScore != null ? `${rangeNumber(selectedRange.confidenceScore * 100, 0)}%` : selectedRange.confidence ?? "未提供"} · {rangeEvidence(selectedRange.source)}</p><p>{rangeCoverage(selectedRange)}</p><p>最近变化：{rangeChange(selectedRange.changeReason)}</p>{selectedRange.topClasses?.length ? <p>主要牌类：{selectedRange.topClasses.slice(0, 3).map((item) => `${item.hand} ${rangeNumber(Number(item.probabilityMass) * 100)}%`).join(" · ")}</p> : null}{movers.length ? <p data-testid="range-top-movers">Top movers（同手同座位）：{movers.map((item) => `${item.hand} ${item.delta > 0 ? "+" : ""}${rangeNumber(item.delta * 100, 1)}%`).join(" · ")}</p> : <p className="tv2-range-unavailable">Top movers 暂不可用：需同手、同座位的上一公开行动 Range 快照。</p>}<button className="tv2-expand-range" onClick={() => setExplorerOpen(true)}>展开矩阵</button></> : <p>{rangeMessage(selectedRange?.unavailableReason)}</p>}</> : <p>{rangeMessage()}</p>;
  const advisor = insights?.advisor;
  const advisorAction = reconciliation?.ruleBaseline.action;
  const solverAction = reconciliation?.simulationEstimate.action;
  const ordered = solver ? [...solver.candidates].sort((a, b) => candidateDelta(b, solver.candidates) - candidateDelta(a, solver.candidates)) : [];
  const displayed = showAllSizes ? ordered : ordered.slice(0, 3);
  const heroStack = table?.seats?.find((seat) => seat.seatId === table.heroSeat)?.stack;
  const spr = heroStack != null && table?.pot ? heroStack / table.pot : null;
  const solverContent = solverLoading ? <p>模拟估计计算中；规则基线仍可用。</p> : solver?.status === "ready" || solver?.status === "degraded" ? <><div className="tv2-ladder" aria-label="Solver Action Ladder">{displayed.map((candidate) => <article key={`${candidate.action}-${candidate.amount ?? ""}`} className="tv2-ladder-row"><strong>{candidateLabel(candidate)}</strong><span>ΔEV {ev(candidateDelta(candidate, solver.candidates))}</span><span>EV {ev(candidate.approximateEvChips)}</span>{candidate.deltaEvConfidenceInterval95 ? <small>ΔEV CI {ev(candidate.deltaEvConfidenceInterval95.lower)}–{ev(candidate.deltaEvConfidenceInterval95.upper)}</small> : null}{candidate.recommendationTier === "close" ? <small>接近最优</small> : null}{candidate.uncertaintyStatus === "not_available" ? <small className="risk">不确定性不可用</small> : null}{candidate.sizingClass === "overbet" || candidate.sizingClass === "jam" ? <small className="risk">极端尺度：{candidate.sizingClass === "jam" ? "全压" : "超池"}</small> : null}</article>)}</div>{ordered.length > 3 ? <button className="tv2-all-sizes" onClick={() => setShowAllSizes((value) => !value)}>{showAllSizes ? "收起尺度" : `全部尺度（${ordered.length}）`}</button> : null}<details><summary>模型详情</summary><p>{solver.status === "degraded" ? "近似 EV 求解（降级）" : "近似 EV 求解"}，不是 GTO、Nash 或最终行动裁决。</p><p>尺度 {solver.sizingRobustness === "robust" ? "稳健" : solver.sizingRobustness === "close" ? "接近" : "不确定"} · 原因 {solver.recommendationReasonCodes?.join(" · ") || "后端未提供"}</p><p>权益 {percent(solver.equity)} · 样本 {solver.sampleCount ?? solver.iterations} · ESS {solver.effectiveSampleSize ?? "—"} · 耗时 {solverElapsedMs != null ? `${solverElapsedMs}ms` : solver.elapsedMicroseconds != null ? `${Math.round(solver.elapsedMicroseconds / 1000)}ms` : "未测得"}</p>{ordered[0]?.responseMix ? <p>最佳候选响应 F/C/R {percent(ordered[0].responseMix.fold)}/{percent(ordered[0].responseMix.call)}/{percent(ordered[0].responseMix.raise)}</p> : null}<p>预算 {solver.budgetTier ?? "未提供"} / {solver.budgetMs ?? "—"}ms · 置信度 {solver.confidence ?? "未提供"}</p><p>限制：{solver.limitations.join("；") || "后端未返回限制"}</p></details></> : <p>{solver?.unavailableReason ?? "当前不是 Hero 决策；模拟估计尚未就绪。"}</p>;
  return <><aside className="tv2-rail" data-testid="table-insights" aria-label="决策驾驶舱"><section className="tv2-summary" aria-label="Decision Summary"><p>轮到 Hero · {table?.street ?? "等待开局"} · Pot {chips(table?.pot)}{spr != null ? ` · SPR ${spr.toFixed(1)}` : " · SPR 暂不可用"}</p><div><span>规则基线</span><strong>Advisor：{advisorAction ? candidateLabel(advisorAction) : reconciliation?.ruleBaseline.unavailableReason ?? advisor?.unavailableReason ?? "暂不可用"}</strong></div><div><span>模拟估计</span><strong>Solver：{solverAction ? candidateLabel(solverAction) : solverLoading ? "计算中" : reconciliation?.simulationEstimate.unavailableReason ?? "暂不可用"}</strong></div><b className={reconciliation?.agreement.kind === "different_action" ? "disagreement" : "agreement"}>{reconciliationText(reconciliation)}</b></section><section className="tv2-analysis-panel" aria-label="Solver 结果"><h2>模拟估计</h2>{solverContent}</section><section className="tv2-analysis-panel tv2-range-summary" aria-label="Range Belief"><h2>Range 摘要</h2><p>座位独立边际估计，不含对手私牌</p>{rangeContent}</section></aside>{explorerOpen && selectedRange?.available ? <RangeExplorer belief={selectedRange} previous={baseline} baselineAvailable={Boolean(baseline)} onClose={() => setExplorerOpen(false)} /> : null}</>;
}

export function TableTimelineV2({ table }: { table: ContinuousTable }) {
  const provenance = new Map(table.botDecisionProvenance.map((item) => [item.sequence, item]));
  return <section className="tv2-timeline" aria-label="行动时间线"><h3>行动时间线</h3><ol data-testid="table-action-history">{table.actionHistory.map((action) => { const source = provenance.get(action.sequence); return <li key={action.sequence}><time>{action.street}</time><span>座位 {action.actorSeat + 1} {actionNames[action.action] ?? action.action}{action.amount != null ? ` ${action.amount}` : ""}</span>{source ? <small>Bot 来源：{source.profileId} · {source.provider}{source.degraded ? ` · 降级${source.fallbackReason ? `：${source.fallbackReason}` : ""}` : ""}</small> : null}</li>; })}</ol><ul data-testid="bot-provenance" className="sr-only">{table.botDecisionProvenance.map((item) => <li key={item.sequence}>座位 {item.actorSeat + 1} · {item.profileId} · {item.provider}</li>)}</ul></section>;
}

export function TableWorkspaceV2({ table, insights, solver, reconciliation, solverLoading, solverElapsedMs, playbackActions = [], playbackIdentity, playbackSpeed, onPlaybackComplete, actionDisabled, amounts, onAmountChange, onAction, onNextHand, review }: {
  table: ContinuousTable; insights: TableInsightsResponse["insights"] | null; solver: TableSolverResponse["solver"] | null; reconciliation: TableReconciliationResponse["reconciliation"] | null; solverLoading: boolean; solverElapsedMs: number | null;
  playbackActions?: readonly ActionDelta[]; playbackIdentity: string; playbackSpeed: PlaybackSpeed; onPlaybackComplete: () => void; actionDisabled: boolean;
  amounts: Record<string, string>; onAmountChange: (action: string, amount: string) => void; onAction: (action: ContinuousTable["heroLegalActions"][number]) => void; onNextHand: () => void; review: TableReviewResponse["review"] | null;
}) {
  const [currentAction, setCurrentAction] = useState<ActionDelta>();
  const [thinkingAction, setThinkingAction] = useState<ActionDelta>();
  const reducedMotion = typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const seats = useMemo(() => seatViews(table), [table]);
  return <main className="tv2-workspace" data-testid="table-workspace-v2"><ActionPlaybackController actions={playbackActions} identity={playbackIdentity} speed={playbackSpeed} reducedMotion={reducedMotion} onChange={setCurrentAction} onThinking={setThinkingAction} onComplete={() => { setThinkingAction(undefined); setCurrentAction(undefined); onPlaybackComplete(); }} />{reducedMotion && <p className="tv2-motion-note" data-testid="reduced-motion-status">动画已简化；公开动作文字即时显示。</p>}<PokerTableStageV2 seats={seats} currentAction={currentAction} thinkingAction={thinkingAction} board={table.board.map(formatCard)} pot={table.pot.toLocaleString("zh-CN")} /><InsightRailV2 table={table} insights={insights} solver={solver} reconciliation={reconciliation} solverLoading={solverLoading} solverElapsedMs={solverElapsedMs} /><TableTimelineV2 table={table} /><HeroActionDockV2 table={table} advisor={insights?.advisor} disabled={actionDisabled} amounts={amounts} onAmountChange={onAmountChange} onAction={onAction} onNextHand={onNextHand} review={review} /></main>;
}
