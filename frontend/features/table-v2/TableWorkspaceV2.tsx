"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { formatCard } from "../../lib/poker/cards";
import { RANKS, matrixCell } from "../../lib/poker/matrix";
import type { ContinuousTable, TableInsightsResponse, TableReviewResponse, TableSolverResponse } from "../../types/api";
import "../../styles/table-v2.css";

export type SeatStatus = "current" | "folded" | "all-in" | "showdown" | "dealer" | "waiting";
export type TableSeat = { id: string; name: string; stack: string; position: string; status: SeatStatus; cards?: string[] };
export type ActionDelta = { id: string; actor: string; label: string; kind: "action" | "raise" | "all-in" | "showdown"; potDelta?: string };
export type PlaybackSpeed = "slow" | "standard" | "fast" | "skip";
export type Scheduler = { setTimeout: (fn: () => void, ms: number) => number; clearTimeout: (id: number | undefined) => void };

const durations: Record<ActionDelta["kind"], number> = { action: 650, raise: 1000, "all-in": 1000, showdown: 1300 };
const multipliers: Record<Exclude<PlaybackSpeed, "skip">, number> = { slow: 1.65, standard: 1, fast: 0.45 };
const actionNames: Record<string, string> = { fold: "弃牌", check: "过牌", call: "跟注", bet: "下注", raise: "加注", raise_to: "加注", all_in: "全下" };

export class ActionPlaybackQueue {
  private timer: number | undefined;
  private token = 0;
  constructor(private readonly scheduler: Scheduler, private readonly reducedMotion = false) {}
  play(actions: readonly ActionDelta[], speed: PlaybackSpeed, onAction: (action: ActionDelta) => void, onComplete?: () => void) {
    this.cancel();
    const token = ++this.token;
    if (speed === "skip" || this.reducedMotion) { actions.forEach(onAction); onComplete?.(); return; }
    let index = 0;
    const next = () => {
      if (token !== this.token) return;
      const action = actions[index++];
      if (!action) { onComplete?.(); return; }
      onAction(action);
      this.timer = this.scheduler.setTimeout(next, durations[action.kind] * multipliers[speed]);
    };
    next();
  }
  cancel() { this.token++; if (this.timer !== undefined) this.scheduler.clearTimeout(this.timer); this.timer = undefined; }
}

export function ActionPlaybackController({ actions, identity, speed, reducedMotion, scheduler, onChange, onComplete }: {
  actions: readonly ActionDelta[]; identity: string; speed: PlaybackSpeed; reducedMotion: boolean; scheduler?: Scheduler;
  onChange: (action?: ActionDelta) => void; onComplete: () => void;
}) {
  const queue = useRef<ActionPlaybackQueue | null>(null);
  const callbacks = useRef({ onChange, onComplete });
  callbacks.current = { onChange, onComplete };
  useEffect(() => {
    queue.current = new ActionPlaybackQueue(scheduler ?? window, reducedMotion);
    if (!actions.length) { callbacks.current.onChange(undefined); callbacks.current.onComplete(); return () => queue.current?.cancel(); }
    queue.current.play(actions, speed, (action) => callbacks.current.onChange(action), () => callbacks.current.onComplete());
    return () => queue.current?.cancel();
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

export function PokerTableStageV2({ seats = defaultSeats, currentAction, board = ["Q♠", "J♥", "4♣"], pot = "1,240" }: { seats?: TableSeat[]; currentAction?: ActionDelta; board?: string[]; pot?: string }) {
  return <section className="tv2-stage" aria-label="六人德州扑克牌桌">
    <div className="tv2-felt" />
    <div className="tv2-safe-zone" aria-label="底池与公共牌安全区"><div className="tv2-pot">底池 <strong>{pot}</strong></div><div className="tv2-board" aria-label="公共牌">{board.length ? board.map((card, index) => <i key={`${card}-${index}`}>{card}</i>) : <span>等待公共牌</span>}</div></div>
    {seats.map((seat, index) => <article className={`tv2-seat tv2-seat-${index} is-${seat.status}`} data-seat={seat.id} key={seat.id} aria-label={`${seat.position} ${seat.name} ${seat.status}`}><span className="tv2-position">{seat.position}</span><div className="tv2-avatar">{seat.name.slice(0, 1)}</div><div className="tv2-player"><b>{seat.name}</b><small>{seat.stack}</small></div>{seat.cards?.length ? <div className="tv2-holecards">{seat.cards.map((card, cardIndex) => <i key={`${card}-${cardIndex}`} aria-label={card}>{card}</i>)}</div> : null}{seat.status === "folded" && <span className="tv2-fold">弃牌</span>}</article>)}
    {currentAction && <div className="tv2-action-bubble" data-testid="bot-action-bubble" aria-live="polite">{currentAction.actor} · {currentAction.label}{currentAction.potDelta ? ` ${currentAction.potDelta}` : ""}</div>}
  </section>;
}

export function HeroActionDockV2({ table, disabled = false, amounts = {}, onAmountChange, onAction, onNextHand, review }: {
  table?: ContinuousTable; disabled?: boolean; amounts?: Record<string, string>; onAmountChange?: (action: string, amount: string) => void;
  onAction?: (action: ContinuousTable["heroLegalActions"][number]) => void; onNextHand?: () => void; review?: TableReviewResponse["review"] | null;
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
  if (table?.handComplete) return <section className="tv2-dock" aria-label="Hero 操作区"><div><small>本手已结算</small><strong data-testid="table-review-status">{review ? `复盘可用：${review.heroDecisions.length} 个 Hero 决策` : "复盘未就绪"}</strong></div><button className="primary" disabled={disabled} onClick={onNextHand} data-testid="next-hand">下一手</button></section>;
  return <section className="tv2-dock" aria-label="Hero 操作区" aria-busy={disabled}><div><small>{disabled ? "Bot 行动播放中" : "轮到你 · 按 F / C / R 快捷操作"}</small><strong>{table ? `Hero · ${table.heroHoleCards.map(formatCard).join(" ")}` : "Hero"}</strong></div><div className="tv2-actions" data-testid="hero-legal-actions">{legalActions.map((legal) => <div key={legal.action}>{legal.minAmount != null && <input aria-label={`${legal.action} amount`} type="number" min={legal.minAmount} max={legal.maxAmount} value={amounts[legal.action] ?? String(legal.minAmount)} disabled={disabled} onChange={(event) => onAmountChange?.(legal.action, event.target.value)} />}<button aria-label={actionNames[legal.action] ?? legal.action} disabled={disabled} onClick={() => onAction?.(legal)} data-testid={`hero-action-${legal.action}`}>{actionNames[legal.action] ?? legal.action}{legal.minAmount != null ? ` ${legal.minAmount}-${legal.maxAmount}` : ""} {legal.action === "fold" ? <kbd>F</kbd> : legal.action === "call" ? <kbd>C</kbd> : legal.action === "raise" ? <kbd>R</kbd> : null}</button></div>)}</div></section>;
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
function RangeHeatmap({ belief }: { belief: NonNullable<TableInsightsResponse["insights"]["seatBeliefs"]>[number] }) {
  const matrix = belief.matrix169;
  if (!matrix) return null;
  return <div className="tv2-range-heatmap" aria-label={`座位 ${belief.seatId + 1} Range 热图`}>
    {RANKS.flatMap((_, row) => RANKS.map((__, column) => {
      const hand = matrixCell(row, column); const cell = matrix[hand]; const mass = Number(cell?.probabilityMass ?? 0);
      return <button type="button" key={hand} className="tv2-range-cell" style={{ "--range-mass": Math.min(1, mass * 10) } as React.CSSProperties} title={`${hand}：概率质量 ${(mass * 100).toFixed(2)}%，${cell?.comboCount ?? 0} 个合法组合`}>{hand}</button>;
    }))}
  </div>;
}
function statText(stats: NonNullable<TableInsightsResponse["insights"]["stats"]>) {
  return stats.bySeat.map((stat) => `座位 ${stat.seatId + 1}：入池率 ${(stat.vpip * 100).toFixed(0)}% · 翻前加注率 ${(stat.pfr * 100).toFixed(0)}% · 3Bet ${(stat.threeBet * 100).toFixed(0)}%`).join("；");
}

export function InsightRailV2({ insights, solver, solverLoading = false, solverElapsedMs }: { insights?: TableInsightsResponse["insights"] | null; solver?: TableSolverResponse["solver"] | null; solverLoading?: boolean; solverElapsedMs?: number | null }) {
  const [tab, setTab] = useState("Advisor");
  const [rangeSeatId, setRangeSeatId] = useState<number | null>(null);
  const range = insights?.seatBeliefs ?? [];
  const selectedRange = range.find((belief) => belief.seatId === rangeSeatId) ?? range.find((belief) => belief.available) ?? range[0];
  const advisor = insights?.advisor;
  const stats = insights?.stats;
  const content = tab === "Range" ? <><p>Range Belief（座位独立边际估计，不含对手私牌）</p>{range.length ? <><div className="tv2-range-seats">{range.map((belief) => <button key={belief.seatId} aria-pressed={selectedRange?.seatId === belief.seatId} onClick={() => setRangeSeatId(belief.seatId)}>座位 {belief.seatId + 1}</button>)}</div>{selectedRange?.available ? <><p>范围宽度 {selectedRange.rangeWidthPct?.toFixed(1) ?? "—"}% · 置信度 {selectedRange.confidence === "heuristic" ? "启发式" : selectedRange.confidence ?? "未提供"}</p><p>最近变化：{selectedRange.changeReason ?? "初始先验"}{selectedRange.approximate ? ` · ${approximationLabel(selectedRange.approximationReason)}` : ""}</p><RangeHeatmap belief={selectedRange} /><small>来源 {selectedRange.source} · {selectedRange.version}。限制：{selectedRange.limitations?.join("；") ?? "未提供"}</small></> : <p>{rangeMessage(selectedRange?.unavailableReason)}</p>}</> : <p>{rangeMessage()}</p>}</> : tab === "Solver" ? <>{solverLoading ? <p>Fast Solver 计算中；Advisor 仍可用。</p> : solver?.status === "ready" || solver?.status === "degraded" ? <><p>{solver.status === "degraded" ? "近似 EV 求解（降级）" : "近似 EV 求解"}，不是 GTO 或 Nash。</p><p>权益 {solver.equity ?? "未返回"} · 迭代 {solver.iterations} · 耗时 {solverElapsedMs != null ? `${solverElapsedMs}ms` : "未测得"}</p>{solver.candidates.map((candidate) => <div className="tv2-ev" key={`${candidate.action}-${candidate.amount ?? ""}`}><span>{actionNames[candidate.action] ?? candidate.action}{candidate.amount != null ? ` ${candidate.amount}` : ""}</span><b>EV {candidate.approximateEvChips}</b></div>)}<small>来源 {solver.source} · {solver.version}。限制：{solver.limitations.join("；") || "后端未返回限制"}</small></> : <p>{solver?.unavailableReason ?? "当前不可用"}</p>}</> : tab === "Stats" ? <p>{stats?.available ? statText(stats) : stats?.unavailableReason ?? "统计未就绪"}</p> : <>{advisor?.available ? <><p>建议：{actionNames[advisor.result?.recommendedAction?.action ?? ""] ?? advisor.result?.recommendedAction?.action ?? "无建议"}</p><small>来源 {advisor.result?.source ?? advisor.provenance?.source ?? "未提供"} · {advisor.result?.version ?? advisor.provenance?.version ?? "版本未提供"}</small></> : <p>{advisor?.unavailableReason ?? "Advisor 未就绪"}</p>}<p className="tv2-honest-empty">公式/启发式建议，不是 Solver 或 GTO 结果。</p></>;
  return <aside className="tv2-rail" data-testid="table-insights" aria-label="分析洞察"><nav>{["Advisor", "Range", "Solver", "Stats"].map((name) => <button key={name} aria-selected={tab === name} onClick={() => setTab(name)}>{name}</button>)}</nav><div className="tv2-rail-content">{content}</div></aside>;
}

export function TableTimelineV2({ table }: { table: ContinuousTable }) {
  const provenance = new Map(table.botDecisionProvenance.map((item) => [item.sequence, item]));
  return <section className="tv2-timeline" aria-label="行动时间线"><h3>行动时间线</h3><ol data-testid="table-action-history">{table.actionHistory.map((action) => { const source = provenance.get(action.sequence); return <li key={action.sequence}><time>{action.street}</time><span>座位 {action.actorSeat + 1} {actionNames[action.action] ?? action.action}{action.amount != null ? ` ${action.amount}` : ""}</span>{source ? <small>Bot 来源：{source.profileId} · {source.provider}{source.degraded ? ` · 降级${source.fallbackReason ? `：${source.fallbackReason}` : ""}` : ""}</small> : null}</li>; })}</ol><ul data-testid="bot-provenance" className="sr-only">{table.botDecisionProvenance.map((item) => <li key={item.sequence}>座位 {item.actorSeat + 1} · {item.profileId} · {item.provider}</li>)}</ul></section>;
}

export function TableWorkspaceV2({ table, insights, solver, solverLoading, solverElapsedMs, playbackActions = [], playbackIdentity, playbackSpeed, onPlaybackComplete, actionDisabled, amounts, onAmountChange, onAction, onNextHand, review }: {
  table: ContinuousTable; insights: TableInsightsResponse["insights"] | null; solver: TableSolverResponse["solver"] | null; solverLoading: boolean; solverElapsedMs: number | null;
  playbackActions?: readonly ActionDelta[]; playbackIdentity: string; playbackSpeed: PlaybackSpeed; onPlaybackComplete: () => void; actionDisabled: boolean;
  amounts: Record<string, string>; onAmountChange: (action: string, amount: string) => void; onAction: (action: ContinuousTable["heroLegalActions"][number]) => void; onNextHand: () => void; review: TableReviewResponse["review"] | null;
}) {
  const [currentAction, setCurrentAction] = useState<ActionDelta>();
  const reducedMotion = typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const seats = useMemo(() => seatViews(table), [table]);
  return <main className="tv2-workspace" data-testid="table-workspace-v2"><ActionPlaybackController actions={playbackActions} identity={playbackIdentity} speed={playbackSpeed} reducedMotion={reducedMotion} onChange={setCurrentAction} onComplete={() => { setCurrentAction(undefined); onPlaybackComplete(); }} /><PokerTableStageV2 seats={seats} currentAction={currentAction} board={table.board.map(formatCard)} pot={table.pot.toLocaleString("zh-CN")} /><InsightRailV2 insights={insights} solver={solver} solverLoading={solverLoading} solverElapsedMs={solverElapsedMs} /><TableTimelineV2 table={table} /><HeroActionDockV2 table={table} disabled={actionDisabled} amounts={amounts} onAmountChange={onAmountChange} onAction={onAction} onNextHand={onNextHand} review={review} /></main>;
}
