"use client";

import { useMemo, useState } from "react";

type ActionEvent = {
  actionId: string;
  sequence: number;
  street: string;
  actorSeat: number;
  actionType: string;
  amount?: number;
  amountType?: string;
};

type Scenario = {
  schemaVersion: number;
  gameVariant: string;
  tableSize: number;
  smallBlind: number;
  bigBlind: number;
  buttonSeat: number;
  heroSeat: number;
  seats: { seatId: number; startingStack: number; position: string }[];
  heroHoleCards: string[];
  villainHoleCards?: string[];
  board: string[];
  actionHistory: ActionEvent[];
  decisionPoint: { street: string; actorSeat: number; afterSequence: number };
  assumptions: Record<string, unknown>;
  villainRange?: Record<string, unknown>;
};

type StateResponse = {
  finalState: {
    street: string;
    actorSeat: number | null;
    board: string[];
    pot: number;
    stacks: Record<string, number>;
    bets: Record<string, number>;
    legalActions: {
      actorSeat: number | null;
      actions: string[];
      callAmount: number | null;
      minRaiseTo: number | null;
      maxRaiseTo: number | null;
      explanations: Record<string, string>;
    };
  };
};

type AnalysisResponse = {
  analysis: {
    metrics: Record<string, string | number | null>;
    hand: { category: string; madeHand: string; draws: string[]; outCount: number };
    board: { labels: string[]; staticOrDynamic: string; nutComboCount: number };
    equity: { heroEquity: string; villainEquity: string; tieProbability: string; sourceLevel: string } | null;
    evidence: { items: { evidenceId: string; kind: string; value: unknown; sourceLevel: string; description: string }[] };
    warnings: string[];
  };
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

const initialScenario: Scenario = {
  schemaVersion: 1,
  gameVariant: "nlhe",
  tableSize: 2,
  smallBlind: 50,
  bigBlind: 100,
  buttonSeat: 0,
  heroSeat: 0,
  seats: [
    { seatId: 0, startingStack: 10_000, position: "button" },
    { seatId: 1, startingStack: 10_000, position: "big_blind" },
  ],
  heroHoleCards: ["As", "Kd"],
  villainHoleCards: ["Qh", "Jc"],
  board: [],
  actionHistory: [],
  decisionPoint: { street: "preflop", actorSeat: 0, afterSequence: 0 },
  assumptions: {},
};

export default function Home() {
  const [scenario, setScenario] = useState<Scenario>(initialScenario);
  const [state, setState] = useState<StateResponse["finalState"] | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisResponse["analysis"] | null>(null);
  const [rangeText, setRangeText] = useState("22+, A5s+, K9o+");
  const [rangeCells, setRangeCells] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("先输入牌面，再使用合法动作按钮推进牌局。");

  const currentStreet = state?.street ?? scenario.decisionPoint.street;
  const legal = state?.legalActions;
  const boardInput = useMemo(() => [...scenario.board, "", "", "", "", ""].slice(0, 5), [scenario.board]);

  function updateScenario(patch: Partial<Scenario>) {
    setScenario((current) => ({ ...current, ...patch }));
    setAnalysis(null);
    setMessage("场景已修改，需要重新校验或分析。");
  }

  function updateCards(field: "heroHoleCards" | "villainHoleCards", index: number, value: string) {
    const cards = [...(scenario[field] ?? ["", ""])] as string[];
    cards[index] = value.trim();
    updateScenario({ [field]: cards } as Partial<Scenario>);
  }

  function updateBoard(index: number, value: string) {
    const board = [...boardInput];
    board[index] = value.trim();
    updateScenario({ board: board.filter(Boolean) });
  }

  async function request(path: string, body: unknown) {
    const response = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error?.message ?? "请求失败");
    return payload;
  }

  async function refreshState(nextScenario = scenario) {
    setBusy(true);
    try {
      const payload = await request("/v1/scenarios/state", nextScenario);
      setState(payload.finalState);
      setScenario((current) => ({
        ...current,
        decisionPoint: {
          street: payload.finalState.street,
          actorSeat: payload.finalState.actorSeat ?? current.heroSeat,
          afterSequence: current.actionHistory.length,
        },
      }));
      setMessage("规则校验通过，当前状态已更新。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "规则校验失败");
    } finally {
      setBusy(false);
    }
  }

  async function appendAction(actionType: string) {
    if (!legal?.actorSeat && legal?.actorSeat !== 0) return;
    const amount = actionType === "call" ? legal.callAmount ?? undefined : actionType === "raise_to" ? legal.minRaiseTo ?? undefined : undefined;
    const amountType = actionType === "call" ? "cost" : actionType === "raise_to" ? "to" : undefined;
    const event: ActionEvent = {
      actionId: `${actionType}-${Date.now()}`,
      sequence: scenario.actionHistory.length + 1,
      street: currentStreet,
      actorSeat: legal.actorSeat,
      actionType,
      ...(amount === undefined ? {} : { amount }),
      ...(amountType === undefined ? {} : { amountType }),
    };
    const next = { ...scenario, actionHistory: [...scenario.actionHistory, event] };
    setScenario(next);
    await refreshState(next);
  }

  async function deal(street: "deal_flop" | "deal_turn" | "deal_river") {
    const next = {
      ...scenario,
      actionHistory: [
        ...scenario.actionHistory,
        {
          actionId: `${street}-${Date.now()}`,
          sequence: scenario.actionHistory.length + 1,
          street: street.replace("deal_", ""),
          actorSeat: state?.actorSeat ?? scenario.heroSeat,
          actionType: street,
        },
      ],
    };
    setScenario(next);
    await refreshState(next);
  }

  async function runAnalysis() {
    setBusy(true);
    try {
      const payload = await request("/v1/analysis", scenario);
      setAnalysis(payload.analysis);
      setMessage("分析完成。所有定量结果都来自结构化证据。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "分析失败");
    } finally {
      setBusy(false);
    }
  }

  async function saveScenario() {
    setBusy(true);
    try {
      await request("/v1/scenarios", { scenario, title: "Manual review", tags: [currentStreet] });
      setMessage("场景已保存，可在历史记录中复制和重新分析。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存失败");
    } finally {
      setBusy(false);
    }
  }

  async function parseRange() {
    try {
      const payload = await request("/v1/ranges/parse", { notation: rangeText });
      setRangeCells(Object.keys(payload.range.matrix169));
      updateScenario({ villainRange: payload.range });
      setMessage(`范围已标准化为 ${Object.keys(payload.range.matrix169).length} 个矩阵格。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "范围解析失败");
    }
  }

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">RIVERLINE / HU NLHE</p>
          <h1>Decision Lab</h1>
        </div>
        <div className="status-pill"><span className="pulse" />本地规则核心在线</div>
      </header>

      <div className="workspace-grid">
        <section className="panel editor-panel">
          <div className="panel-heading">
            <div><p className="eyebrow">01 · SCENARIO</p><h2>构造决策场景</h2></div>
            <span className="muted">{scenario.actionHistory.length} events</span>
          </div>

          <div className="table-card">
            <div className="felt">
              <div className="seat seat-left"><span>BB · Seat 1</span><strong>{state?.stacks["1"] ?? "10,000"}</strong></div>
              <div className="board-row">
                {boardInput.map((card, index) => <span className={`board-card ${card ? "filled" : "empty"}`} key={index}>{card || "·"}</span>)}
              </div>
              <div className="pot-label">POT <strong>{state?.pot ?? 150}</strong></div>
              <div className="seat seat-right"><span>BTN · Hero</span><strong>{state?.stacks["0"] ?? "9,950"}</strong></div>
            </div>
          </div>

          <div className="form-grid">
            <label>Hero 手牌<input value={scenario.heroHoleCards.join(" ")} onChange={(event) => updateScenario({ heroHoleCards: event.target.value.split(/\s+/).filter(Boolean).slice(0, 2) })} /></label>
            <label>Villain 手牌<input value={(scenario.villainHoleCards ?? []).join(" ")} onChange={(event) => updateScenario({ villainHoleCards: event.target.value.split(/\s+/).filter(Boolean).slice(0, 2) })} /></label>
          </div>
          <div className="card-inputs">
            {boardInput.map((card, index) => <input aria-label={`board-${index}`} key={index} value={card} placeholder={index < 3 ? `牌面 ${index + 1}` : "future"} onChange={(event) => updateBoard(index, event.target.value)} />)}
          </div>

          <div className="action-box">
            <div className="action-header"><span>当前节点 · {currentStreet}</span><span className="muted">行动者 Seat {legal?.actorSeat ?? state?.actorSeat ?? 0}</span></div>
            <div className="action-buttons">
              {legal?.actions.includes("check") && <button onClick={() => appendAction("check")} disabled={busy}>Check</button>}
              {legal?.actions.includes("call") && <button onClick={() => appendAction("call")} disabled={busy}>Call {legal.callAmount}</button>}
              {legal?.actions.includes("raise_to") && <button onClick={() => appendAction("raise_to")} disabled={busy}>Raise to {legal.minRaiseTo}</button>}
              {legal?.actions.includes("fold") && <button className="quiet" onClick={() => appendAction("fold")} disabled={busy}>Fold</button>}
              {currentStreet === "preflop" && <button className="quiet" onClick={() => deal("deal_flop")} disabled={busy || scenario.board.length < 3}>Deal flop</button>}
              {currentStreet === "flop" && <button className="quiet" onClick={() => deal("deal_turn")} disabled={busy || scenario.board.length < 4}>Deal turn</button>}
              {currentStreet === "turn" && <button className="quiet" onClick={() => deal("deal_river")} disabled={busy || scenario.board.length < 5}>Deal river</button>}
            </div>
          </div>

          <div className="timeline">
            <div className="subheading"><span>行动时间线</span><button className="text-button" onClick={() => refreshState()}>重新校验</button></div>
            {scenario.actionHistory.length === 0 ? <p className="muted">尚未录入行动。后端会从盲注和初始筹码推导底池。</p> : scenario.actionHistory.map((event) => <div className="timeline-row" key={event.actionId}><span className="sequence">{String(event.sequence).padStart(2, "0")}</span><span>{event.street}</span><strong>Seat {event.actorSeat} · {event.actionType}</strong><span className="muted">{event.amount ?? "—"}</span></div>)}
          </div>
        </section>

        <aside className="side-column">
          <section className="panel compact-panel">
            <div className="panel-heading"><div><p className="eyebrow">02 · RANGE</p><h2>Villain 范围</h2></div><span className="source-tag">假设</span></div>
            <textarea value={rangeText} onChange={(event) => setRangeText(event.target.value)} aria-label="range notation" />
            <button className="secondary-button" onClick={parseRange}>标准化范围</button>
            <div className="range-grid">{rangeCells.slice(0, 36).map((cell) => <span key={cell}>{cell}</span>)}{rangeCells.length > 36 && <span>+{rangeCells.length - 36}</span>}</div>
            <p className="muted small">范围权重、dead card 和组合数由后端计算；前端不自行裁决。</p>
          </section>

          <section className="panel compact-panel">
            <div className="panel-heading"><div><p className="eyebrow">03 · ANALYZE</p><h2>输出证据</h2></div><span className="source-tag green">grounded</span></div>
            <p className="muted">编辑完成后重新分析。没有可靠策略数据时，结果只提供数学与原理层证据。</p>
            <div className="primary-actions"><button onClick={() => refreshState()} disabled={busy}>校验场景</button><button onClick={runAnalysis} disabled={busy}>生成分析</button><button className="secondary-button" onClick={saveScenario} disabled={busy}>保存场景</button></div>
            <p className="notice">{message}</p>
          </section>
        </aside>
      </div>

      {analysis && <section className="panel results-panel">
        <div className="panel-heading"><div><p className="eyebrow">04 · EVIDENCE BUNDLE</p><h2>结构化分析</h2></div><span className="source-tag green">{analysis.equity?.sourceLevel ?? "principle_only"}</span></div>
        <div className="metric-grid">
          <Metric label="Pot" value={analysis.metrics.currentPot ?? "—"} />
          <Metric label="Call cost" value={analysis.metrics.callCost ?? "—"} />
          <Metric label="SPR" value={analysis.metrics.spr ?? "—"} />
          <Metric label="Pot odds" value={analysis.metrics.potOdds ?? "—"} />
          <Metric label="Hand" value={analysis.hand.madeHand} />
          <Metric label="Outs" value={analysis.hand.outCount} />
        </div>
        <div className="result-columns">
          <div><p className="eyebrow">HAND / BOARD</p><p className="result-line"><strong>{analysis.hand.category}</strong> · {analysis.hand.draws.join(", ") || "no draw"}</p><p className="muted">Board: {analysis.board.labels.join(" · ")} · {analysis.board.staticOrDynamic}</p></div>
          <div><p className="eyebrow">EQUITY</p>{analysis.equity ? <p className="result-line"><strong>{analysis.equity.heroEquity}</strong> Hero · {analysis.equity.villainEquity} Villain · tie {analysis.equity.tieProbability}</p> : <p className="muted">缺少 Villain 手牌或范围，未计算 Equity。</p>}</div>
        </div>
        <div className="evidence-list">{analysis.evidence.items.slice(0, 12).map((item) => <div className="evidence-row" key={item.evidenceId}><span>{item.evidenceId}</span><strong>{String(item.value)}</strong><em>{item.sourceLevel}</em><small>{item.description}</small></div>)}</div>
        {analysis.warnings.map((warning) => <p className="warning" key={warning}>{warning}</p>)}
      </section>}

      <footer><span>ScenarioSpec → Replay → EvidenceBundle</span><span>无 Solver 频率 · 无自动行动</span></footer>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return <div className="metric"><span>{label}</span><strong>{String(value)}</strong></div>;
}
