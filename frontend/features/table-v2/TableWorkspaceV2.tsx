"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import "../../styles/table-v2.css";

export type SeatStatus = "current" | "folded" | "all-in" | "showdown" | "dealer" | "waiting";
export type TableSeat = { id: string; name: string; stack: string; position: string; status: SeatStatus; cards?: string[] };
export type ActionDelta = { id: string; actor: string; label: string; kind: "action" | "raise" | "all-in" | "showdown"; potDelta?: string };
export type PlaybackSpeed = "slow" | "standard" | "fast" | "skip";
export type Scheduler = { setTimeout: (fn: () => void, ms: number) => number; clearTimeout: (id: number | undefined) => void };

const durations: Record<ActionDelta["kind"], number> = { action: 650, raise: 1000, "all-in": 1000, showdown: 1300 };
const multipliers: Record<Exclude<PlaybackSpeed, "skip">, number> = { slow: 1.65, standard: 1, fast: 0.45 };

export class ActionPlaybackQueue {
  private timer: number | undefined;
  private token = 0;
  constructor(private readonly scheduler: Scheduler = window, private readonly reducedMotion = false) {}
  play(actions: readonly ActionDelta[], speed: PlaybackSpeed, onAction: (action: ActionDelta) => void, onComplete?: () => void) {
    this.cancel(); const token = ++this.token;
    if (speed === "skip" || this.reducedMotion) { actions.forEach(onAction); onComplete?.(); return; }
    let index = 0;
    const next = () => { if (token !== this.token) return; const action = actions[index++]; if (!action) { onComplete?.(); return; } onAction(action); this.timer = this.scheduler.setTimeout(next, durations[action.kind] * multipliers[speed]); };
    next();
  }
  cancel() { this.token++; if (this.timer !== undefined) this.scheduler.clearTimeout(this.timer); this.timer = undefined; }
  hydrateLatest(action?: ActionDelta) { this.cancel(); return action; }
}

export function ActionPlaybackController({ actions, identity, speed = "standard", reducedMotion = false, scheduler, onChange }: { actions: readonly ActionDelta[]; identity: string; speed?: PlaybackSpeed; reducedMotion?: boolean; scheduler?: Scheduler; onChange?: (action?: ActionDelta) => void }) {
  const queue = useRef<ActionPlaybackQueue | null>(null);
  useEffect(() => { queue.current = new ActionPlaybackQueue(scheduler, reducedMotion); queue.current.play(actions, speed, (action) => onChange?.(action)); return () => queue.current?.cancel(); }, [actions, identity, speed, reducedMotion, scheduler, onChange]);
  return null;
}

const defaultSeats: TableSeat[] = [
  { id: "utg", name: "林舟", stack: "¥ 2,480", position: "UTG", status: "folded" },
  { id: "hj", name: "Maya", stack: "¥ 3,120", position: "HJ", status: "waiting" },
  { id: "co", name: "Aron", stack: "¥ 1,860", position: "CO", status: "all-in" },
  { id: "btn", name: "Hero", stack: "¥ 4,560", position: "BTN", status: "current", cards: ["A♠", "J♠"] },
  { id: "sb", name: "小北", stack: "¥ 2,110", position: "SB", status: "showdown", cards: ["K♦", "Q♦"] },
  { id: "bb", name: "Niko", stack: "¥ 2,920", position: "BB", status: "dealer" },
];

export function PokerTableStageV2({ seats = defaultSeats, currentAction }: { seats?: TableSeat[]; currentAction?: ActionDelta }) {
  return <section className="tv2-stage" aria-label="六人德州扑克牌桌"><div className="tv2-felt" />
    <div className="tv2-safe-zone" aria-label="底池与公共牌安全区"><div className="tv2-pot">底池 <strong>¥ 1,240</strong></div><div className="tv2-board" aria-label="公共牌"><i>Q♠</i><i>J♥</i><i>4♣</i></div></div>
    {seats.map((seat, index) => <article className={`tv2-seat tv2-seat-${index} is-${seat.status}`} data-seat={seat.id} key={seat.id} aria-label={`${seat.position} ${seat.name} ${seat.status}`}><span className="tv2-position">{seat.position}</span><div className="tv2-avatar">{seat.name.slice(0, 1)}</div><div className="tv2-player"><b>{seat.name}</b><small>{seat.stack}</small></div>{seat.cards && <div className="tv2-holecards">{seat.cards.map((card) => <i key={card}>{card}</i>)}</div>}{seat.status === "dealer" && <em>D</em>}{seat.status === "folded" && <span className="tv2-fold">弃牌</span>}</article>)}
    {currentAction && <div className="tv2-action-bubble" aria-live="polite">{currentAction.actor} · {currentAction.label}</div>}
  </section>;
}

export function HeroActionDockV2({ disabled = false, onAction }: { disabled?: boolean; onAction?: (action: string) => void }) {
  return <section className="tv2-dock" aria-label="Hero 操作区" aria-busy={disabled}><div><small>轮到你 · 按 F / C / R 快捷操作</small><strong>按钮位 · A♠ J♠</strong></div><div className="tv2-actions"><button aria-label="弃牌" disabled={disabled} onClick={() => onAction?.("fold")}>弃牌 <kbd>F</kbd></button><button aria-label="跟注 120" disabled={disabled} onClick={() => onAction?.("call")}>跟注 ¥120 <kbd>C</kbd></button><button className="primary" aria-label="加注" disabled={disabled} onClick={() => onAction?.("raise")}>加注 <kbd>R</kbd></button></div><label>下注额 <input aria-label="下注额" disabled={disabled} defaultValue="¥ 360" /></label></section>;
}

export type RangeState = { status: "ready" | "unavailable"; width?: string; confidence?: string; reason?: string; message?: string };
export type SolverState = { status: "computing" | "ready" | "degraded" | "unavailable"; message: string; actions?: { label: string; ev: number }[] };
export function InsightRailV2({ range = { status: "ready", width: "22–31%", confidence: "中等", reason: "翻前加注与转牌持续下注" }, solver = { status: "ready", message: "近似求解 · 8,000 个局面", actions: [{ label: "加注", ev: 1.8 }, { label: "跟注", ev: 0.6 }, { label: "弃牌", ev: -1.2 }] } }: { range?: RangeState; solver?: SolverState }) {
  const [tab, setTab] = useState("Advisor"); const content = tab === "Range" ? <><p>{range.status === "unavailable" ? range.message ?? "当前无法估计对手范围。" : `范围宽度 ${range.width} · 置信度 ${range.confidence}`}</p>{range.status === "ready" && <><small>{range.reason}</small><div className="tv2-heatmap" aria-label="13乘13范围热图占位">13 × 13</div></>}</> : tab === "Solver" ? <><p className={`solver-${solver.status}`}>{solver.message}</p>{solver.actions?.map((a) => <div className="tv2-ev" key={a.label}><span>{a.label}</span><b style={{ width: `${Math.max(12, Math.abs(a.ev) * 35)}%` }} className={a.ev < 0 ? "negative" : ""}>{a.ev > 0 ? "+" : ""}{a.ev} bb</b></div>)}</> : <p>{tab === "Advisor" ? "建议：保留跟注与小尺度加注两条线。" : "本局数据将在结算后归档。"}</p>;
  return <aside className="tv2-rail" aria-label="分析洞察"><nav>{["Advisor", "Range", "Solver", "Stats"].map((name) => <button key={name} aria-selected={tab === name} onClick={() => setTab(name)}>{name}</button>)}</nav><div className="tv2-rail-content">{content}</div></aside>;
}

export const tableV2DemoActions: readonly ActionDelta[] = [{ id: "1", actor: "Aron", label: "全下", kind: "all-in", potDelta: "¥1,860" }];
export function TableWorkspaceV2({ disabled = false, actions = tableV2DemoActions }: { disabled?: boolean; actions?: readonly ActionDelta[] }) {
  const [current, setCurrent] = useState<ActionDelta | undefined>(actions[0]); const identity = useMemo(() => actions.map((a) => a.id).join("/"), [actions]);
  return <main className="tv2-workspace"><ActionPlaybackController actions={actions} identity={identity} speed="skip" onChange={setCurrent} /><PokerTableStageV2 currentAction={current} /><InsightRailV2 /><HeroActionDockV2 disabled={disabled} /></main>;
}
