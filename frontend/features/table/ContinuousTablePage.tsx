"use client";

import { useEffect, useRef, useState } from "react";

import PokerTable from "../../components/poker/PokerTable";
import { continuousTableApi } from "../../lib/api/client";
import { cardsToViewModels } from "../../lib/poker/cards";
import type { ContinuousTable, TableInsightsResponse, TableReviewResponse } from "../../types/api";
import type { SeatViewModel } from "../../types/poker";

const profiles = ["cautious", "balanced", "aggressive"] as const;
const positions = ["button", "small_blind", "big_blind", "utg", "utg+1", "mp"];

function commandId(prefix: string) {
  return `${prefix}-${crypto.randomUUID()}`;
}

export default function ContinuousTablePage() {
  const [profile, setProfile] = useState<(typeof profiles)[number]>("balanced");
  const [table, setTable] = useState<ContinuousTable | null>(null);
  const [amounts, setAmounts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [insights, setInsights] = useState<TableInsightsResponse["insights"] | null>(null);
  const [review, setReview] = useState<TableReviewResponse["review"] | null>(null);
  const insightRequest = useRef(0);
  const reviewRequest = useRef(0);
  const reviewIdentity = useRef<string | null>(null);

  function loadInsights(next: ContinuousTable) {
    const request = ++insightRequest.current;
    setInsights(null);
    continuousTableApi.insights(next.sessionId)
      .then((response) => { if (request === insightRequest.current) setInsights(response.insights); })
      .catch(() => { if (request === insightRequest.current) setInsights(null); });
  }
  function loadReview(next: ContinuousTable) {
    const request = ++reviewRequest.current;
    const identity = next.handComplete && next.handId ? `${next.sessionId}:${next.handId}` : null;
    reviewIdentity.current = identity;
    setReview(null);
    if (!identity || !next.handId) return;
    continuousTableApi.reviews(next.sessionId, next.handId)
      .then((response) => { if (request === reviewRequest.current && identity === reviewIdentity.current) setReview(response.review ?? null); })
      .catch(() => { if (request === reviewRequest.current && identity === reviewIdentity.current) setReview(null); });
  }

  useEffect(() => {
    const sessionId = window.localStorage.getItem("riverline-continuous-table-session");
    if (!sessionId) return;
    setBusy(true);
    continuousTableApi.get(sessionId)
      .then((response) => { setTable(response.table); loadInsights(response.table); loadReview(response.table); })
      .catch((cause) => {
        window.localStorage.removeItem("riverline-continuous-table-session");
        setError(cause instanceof Error ? cause.message : "无法重连牌桌");
      })
      .finally(() => setBusy(false));
  }, []);

  async function create() {
    setBusy(true); setError(null);
    try {
      const response = await continuousTableApi.create({ commandId: commandId("create"), botProfile: profile });
      setTable(response.table); loadInsights(response.table); loadReview(response.table);
      window.localStorage.setItem("riverline-continuous-table-session", response.table.sessionId);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "创建牌桌失败");
    } finally { setBusy(false); }
  }

  async function submit(legal: ContinuousTable["heroLegalActions"][number]) {
    if (!table?.handId) return;
    const amount = amounts[legal.action];
    setBusy(true); setError(null);
    try {
      const response = await continuousTableApi.action(table.sessionId, {
        commandId: commandId("hero"), handId: table.handId, expectedRevision: table.revision,
        action: legal.action, amountSemantics: legal.amountSemantics,
        ...(legal.minAmount != null ? { amount: Number(amount || legal.minAmount) } : {}),
      });
      setTable(response.table); loadInsights(response.table); loadReview(response.table);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "行动未被接受"); }
    finally { setBusy(false); }
  }

  async function nextHand() {
    if (!table) return;
    setBusy(true); setError(null);
    try {
      const response = await continuousTableApi.nextHand(table.sessionId, { commandId: commandId("next"), expectedRevision: table.revision });
      setTable(response.table); loadInsights(response.table); loadReview(response.table);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "无法开始下一手"); }
    finally { setBusy(false); }
  }

  const seats: SeatViewModel[] = table?.seats.map((seat) => ({
    seatId: seat.seatId, position: positions[seat.seatId] ?? "seat", label: `Seat ${seat.seatId}`,
    stack: seat.stack, bet: seat.committed,
    cards: seat.seatId === table.heroSeat ? cardsToViewModels(table.heroHoleCards) : [],
    isHero: seat.seatId === table.heroSeat, isDealer: seat.seatId === table.buttonSeat,
    isActor: seat.seatId === table.currentActor, isFolded: seat.status === "folded",
    isAllIn: false, isActive: seat.status === "active",
  })) ?? [];

  return (
    <section className="continuous-table" data-testid="continuous-table-page">
      <div className="panel-heading"><div><h2>持续牌桌</h2><p>Hero + 5 bots · 6-max · 100BB</p></div>
        <label>Bot profile <select value={profile} disabled={busy || !!table} onChange={(event) => setProfile(event.target.value as typeof profile)} data-testid="bot-profile">
          {profiles.map((item) => <option key={item} value={item}>{item}</option>)}
        </select></label>
      </div>
      {!table && <button className="primary" onClick={create} disabled={busy} data-testid="create-continuous-table">{busy ? "连接中…" : "开始牌桌"}</button>}
      {error && <p className="warning" role="alert">{error}</p>}
      {table && <div className="continuous-table__layout">
        <div className="continuous-table__main">
        <p className="muted" data-testid="continuous-table-status">Hand {table.handSequence} · {table.street ?? "等待开局"} · {table.currentActor == null ? "本手结束" : `Seat ${table.currentActor} 行动`}</p>
        <PokerTable seats={seats} board={table.board} pot={table.pot} unit="chips" />
        <div className="continuous-table__action-dock">{table.handComplete ? <><div data-testid="table-review-status">{review ? `复盘可用：${review.heroDecisions.length} 个 Hero 决策` : "复盘未就绪"}</div><button className="primary" onClick={nextHand} disabled={busy} data-testid="next-hand">下一手</button></> :
          <div className="action-buttons" data-testid="hero-legal-actions">
            {table.heroLegalActions.map((legal) => <div key={legal.action}>
              {legal.minAmount != null && <input aria-label={`${legal.action} amount`} type="number" min={legal.minAmount} max={legal.maxAmount} value={amounts[legal.action] ?? legal.minAmount} onChange={(event) => setAmounts({ ...amounts, [legal.action]: event.target.value })} />}
              <button className="action-btn" onClick={() => submit(legal)} disabled={busy} data-testid={`hero-action-${legal.action}`}>{legal.action}{legal.minAmount != null ? ` ${legal.minAmount}-${legal.maxAmount}` : ""}</button>
            </div>)}
          </div>}
        </div>
        <div className="continuous-table__details">
          <section><h3>行动历史</h3><ol data-testid="table-action-history">{table.actionHistory.map((action) => <li key={action.sequence}>Seat {action.actorSeat} {action.action}{action.amount != null ? ` ${action.amount}` : ""}</li>)}</ol></section>
          <section><h3>Bot 来源</h3><ul data-testid="bot-provenance">{table.botDecisionProvenance.map((item) => <li key={item.sequence}>Seat {item.actorSeat} · {item.profileId} · {item.provider}{item.degraded ? " (fallback)" : ""}</li>)}</ul></section>
        </div>
        </div>
        <aside className="notice continuous-table__insights" data-testid="table-insights"><strong>牌桌洞察（只读）</strong>
          {!insights?.available ? <p>洞察未就绪</p> : <div className="insight-sections">
            <section><h3>Advisor</h3><p>{insights.advisor?.available ? `${insights.advisor.result?.recommendedAction?.action ?? "无建议"} · ${insights.advisor.result?.source ?? "来源未提供"}` : insights.advisor?.unavailableReason ?? "当前不可用"}</p><p className="muted small">公式/启发式建议，不是 Solver 或 GTO 结果。</p></section>
            <section><h3>Range</h3>{insights.seatBeliefs?.length ? <ul>{insights.seatBeliefs.map((belief) => <li key={belief.seatId}>Seat {belief.seatId}：{belief.available ? <>{belief.currentMass != null ? `mass ${belief.currentMass} · ` : ""}{belief.provenance?.provider ?? "provider 未提供"} · {belief.provenance?.version ?? "version 未提供"} · {belief.provenance?.trustLevel ?? "trust 未提供"}</> : belief.unavailableReason ?? "不可用"}</li>)}</ul> : <p>当前未返回座位 Range Belief。</p>}<p className="muted small">独立座位边际；不含对手私牌。</p></section>
            <section><h3>Stats</h3><p>{insights.stats?.available ? insights.stats.bySeat.map((stat) => `Seat ${stat.seatId} VPIP ${(stat.vpip * 100).toFixed(0)}% PFR ${(stat.pfr * 100).toFixed(0)}% 3B ${(stat.threeBet * 100).toFixed(0)}%`).join(" · ") : insights.stats?.unavailableReason ?? "当前不可用"}</p></section>
            <section><h3>Solver</h3><p>当前未连接/不可用。</p><p className="muted small">本桌 API 未返回真实 Solver 结果。</p></section>
          </div>}
        </aside>
      </div>}
    </section>
  );
}
