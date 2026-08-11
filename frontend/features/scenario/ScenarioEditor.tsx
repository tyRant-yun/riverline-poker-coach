// Scenario editor: hole cards, blinds, stacks and board input. State lives in
// the workspace; this component only renders and emits patches.
//
// Input affordances:
//   - keyboard text boxes (primary, unchanged)
//   - a 52-card picker attached to every card slot (hero/villain/board)
//   - review mode: fill only your own hand and mark the opponent's cards as
//     unknown (their hole cards are cleared from the scenario)

import { useMemo, useState } from "react";

import CardPicker from "../../components/poker/CardPicker";
import { positionLabel } from "../../lib/poker/positions";
import { getKnownCardsForSeat, heroSeatSpec, opponentSeatSpec } from "../../lib/poker/scenario";
import type { Scenario } from "../../types/scenario";

type Props = {
  scenario: Scenario;
  boardInput: string[];
  busy: boolean;
  canUndo: boolean;
  canRedo: boolean;
  onReset: () => void;
  onUndo: () => void;
  onRedo: () => void;
  onUpdateScenario: (patch: Partial<Scenario>) => void;
  onUpdateBoard: (index: number, value: string) => void;
  onTableSizeChange?: (tableSize: number) => void;
  onButtonSeatChange?: (seatId: number) => void;
  onHeroSeatChange?: (seatId: number) => void;
};

type PickerTarget = "hero" | "villain" | number;

function pickerTargetLabel(target: PickerTarget): string {
  if (target === "hero") return "Hero 手牌";
  if (target === "villain") return "Villain 手牌";
  return `牌面 ${(target as number) + 1}`;
}

export default function ScenarioEditor({
  scenario,
  boardInput,
  busy,
  canUndo,
  canRedo,
  onReset,
  onUndo,
  onRedo,
  onUpdateScenario,
  onUpdateBoard,
  onTableSizeChange,
  onButtonSeatChange,
  onHeroSeatChange,
}: Props) {
  const [pickerTarget, setPickerTarget] = useState<PickerTarget | null>(null);
  const [heroOnlyMode, setHeroOnlyMode] = useState(false);

  const heroSeat = heroSeatSpec(scenario);
  // HU-only fields: the "Villain" slot is only meaningful with two seats.
  const villainSeat = opponentSeatSpec(scenario);
  const isHeadsUp = scenario.tableSize === 2;

  const heroHoleCards = scenario.heroHoleCards ?? [];
  const villainHoleCards = scenario.villainHoleCards ?? [];

  const usedCards = useMemo(
    () => [
      ...scenario.seats.flatMap((seat) => getKnownCardsForSeat(scenario, seat.seatId)),
      ...boardInput.filter(Boolean),
    ],
    [scenario, boardInput],
  );

  function updateKnownSeatCards(seatId: number, value: string) {
    const cards = value.split(/\s+/).filter(Boolean).slice(0, 2);
    const knownHoleCardsBySeat = { ...(scenario.knownHoleCardsBySeat ?? {}) };
    if (cards.length === 2) knownHoleCardsBySeat[String(seatId)] = cards;
    else delete knownHoleCardsBySeat[String(seatId)];
    const patch: Partial<Scenario> = { knownHoleCardsBySeat };
    if (seatId === scenario.heroSeat) patch.heroHoleCards = cards;
    if (isHeadsUp && seatId === villainSeat?.seatId) patch.villainHoleCards = cards;
    onUpdateScenario(patch);
  }

  const handlePick = (card: string) => {
    const lower = card.toLowerCase();
    if (pickerTarget === "hero") {
      const current = scenario.heroHoleCards ?? [];
      if (current.length < 2 && !current.some((c) => c.toLowerCase() === lower)) {
        onUpdateScenario({ heroHoleCards: [...current, card] });
        if (current.length + 1 >= 2) setPickerTarget(null);
      }
    } else if (pickerTarget === "villain") {
      const current = scenario.villainHoleCards ?? [];
      if (current.length < 2 && !current.some((c) => c.toLowerCase() === lower)) {
        onUpdateScenario({ villainHoleCards: [...current, card] });
        if (current.length + 1 >= 2) setPickerTarget(null);
      }
    } else if (typeof pickerTarget === "number") {
      onUpdateBoard(pickerTarget, card);
      setPickerTarget(null);
    }
  };

  const villainUnknown = heroOnlyMode;

  return (
    <>
      <div className="panel-heading">
        <div>
          <p className="eyebrow">01 · SCENARIO</p>
          <h2>构造决策场景</h2>
        </div>
        <div className="heading-actions">
          <span className="muted">{scenario.actionHistory.length} events</span>
          <button className="text-button" onClick={onReset} disabled={busy}>
            重置场景
          </button>
          <button className="icon-button" onClick={onUndo} disabled={!canUndo || busy} aria-label="撤销">
            ↶
          </button>
          <button className="icon-button" onClick={onRedo} disabled={!canRedo || busy} aria-label="重做">
            ↷
          </button>
        </div>
      </div>

      <div className="settings-grid scenario-topology-controls">
        <label>
          桌型
          <select
            aria-label="桌型"
            value={scenario.tableSize}
            onChange={(event) => onTableSizeChange?.(Number(event.target.value))}
          >
            {Array.from({ length: 7 }, (_, index) => index + 2).map((tableSize) => (
              <option key={tableSize} value={tableSize}>{tableSize}-max</option>
            ))}
          </select>
        </label>
        <label>
          按钮位
          <select
            aria-label="按钮位"
            value={scenario.buttonSeat}
            onChange={(event) => onButtonSeatChange?.(Number(event.target.value))}
          >
            {scenario.seats.map((seat) => <option key={seat.seatId} value={seat.seatId}>Seat {seat.seatId}</option>)}
          </select>
        </label>
        <label>
          Hero 座位
          <select
            aria-label="Hero 座位"
            value={scenario.heroSeat}
            onChange={(event) => onHeroSeatChange?.(Number(event.target.value))}
          >
            {scenario.seats.map((seat) => <option key={seat.seatId} value={seat.seatId}>Seat {seat.seatId}</option>)}
          </select>
        </label>
      </div>

      {isHeadsUp && <div className="form-grid">
        <label>
          Hero 手牌
          <span className="card-slot">
            <input
              value={heroHoleCards.join(" ")}
              onChange={(event) =>
                onUpdateScenario({
                  heroHoleCards: event.target.value.split(/\s+/).filter(Boolean).slice(0, 2),
                })
              }
            />
            <button
              type="button"
              className="pick-toggle"
              onClick={() => setPickerTarget(pickerTarget === "hero" ? null : "hero")}
              aria-label="为 Hero 手牌选牌"
              aria-pressed={pickerTarget === "hero"}
            >
              选牌
            </button>
          </span>
        </label>
        {isHeadsUp && (
          <label>
            Villain 手牌
            <span className="card-slot">
              <input
                value={villainUnknown ? "" : villainHoleCards.join(" ")}
                disabled={villainUnknown}
                placeholder={villainUnknown ? "未知" : undefined}
                onChange={(event) =>
                  onUpdateScenario({
                    villainHoleCards: event.target.value.split(/\s+/).filter(Boolean).slice(0, 2),
                  })
                }
              />
              <button
                type="button"
                className="pick-toggle"
                disabled={villainUnknown}
                onClick={() => setPickerTarget(pickerTarget === "villain" ? null : "villain")}
                aria-label="为 Villain 手牌选牌"
                aria-pressed={pickerTarget === "villain"}
              >
                选牌
              </button>
            </span>
          </label>
        )}
      </div>}
      {isHeadsUp && (
        <div className="review-mode">
          <label className="hero-only-toggle">
            <input
              type="checkbox"
              checked={heroOnlyMode}
              onChange={(event) => {
                const enabled = event.target.checked;
                setHeroOnlyMode(enabled);
                if (enabled) {
                  onUpdateScenario({ villainHoleCards: undefined });
                }
              }}
            />
            复盘模式
          </label>
          <p className="muted small">对手手牌未知，只填写 Hero 手牌</p>
        </div>
      )}
      <div className="settings-grid">
        <label>
          小盲
          <input
            type="number"
            min="1"
            value={scenario.smallBlind}
            onChange={(event) => onUpdateScenario({ smallBlind: Number(event.target.value) || 1 })}
          />
        </label>
        <label>
          大盲
          <input
            type="number"
            min="1"
            value={scenario.bigBlind}
            onChange={(event) => onUpdateScenario({ bigBlind: Number(event.target.value) || 1 })}
          />
        </label>
        <label>
          Hero 起始筹码
          <input
            type="number"
            min="1"
            value={heroSeat.startingStack}
            onChange={(event) =>
              onUpdateScenario({
                seats: scenario.seats.map((seat) =>
                  seat.seatId === heroSeat.seatId
                    ? { ...seat, startingStack: Number(event.target.value) || 1 }
                    : seat,
                ),
              })
            }
          />
        </label>
        {isHeadsUp && villainSeat && (
          <label>
            Villain 起始筹码
            <input
              type="number"
              min="1"
              value={villainSeat.startingStack}
              onChange={(event) =>
                onUpdateScenario({
                  seats: scenario.seats.map((seat) =>
                    seat.seatId === villainSeat.seatId
                      ? { ...seat, startingStack: Number(event.target.value) || 1 }
                      : seat,
                  ),
                })
              }
            />
          </label>
        )}
      </div>
      {!isHeadsUp && (
        <div className="seat-editor-grid" aria-label="多座位编辑器">
          {scenario.seats.map((seat) => {
            const cards = getKnownCardsForSeat(scenario, seat.seatId);
            return (
              <article className="seat-editor" key={seat.seatId}>
                <div className="seat-editor__heading">
                  <strong>Seat {seat.seatId}</strong>
                  {seat.seatId === scenario.heroSeat && <span className="source-tag">HERO</span>}
                </div>
                <label>
                  位置
                  <output aria-label={`Seat ${seat.seatId} 位置`}>{positionLabel(seat.position)}</output>
                </label>
                <label>
                  起始筹码
                  <input
                    aria-label={`Seat ${seat.seatId} 起始筹码`}
                    type="number"
                    min="1"
                    value={seat.startingStack}
                    onChange={(event) => onUpdateScenario({
                      seats: scenario.seats.map((candidate) => candidate.seatId === seat.seatId
                        ? { ...candidate, startingStack: Number(event.target.value) || 1 }
                        : candidate),
                    })}
                  />
                </label>
                <label>
                  手牌
                  <input
                    aria-label={`Seat ${seat.seatId} 手牌`}
                    value={cards.join(" ")}
                    placeholder="未知"
                    onChange={(event) => updateKnownSeatCards(seat.seatId, event.target.value)}
                  />
                </label>
              </article>
            );
          })}
        </div>
      )}
      <div className="card-inputs">
        {boardInput.map((card, index) => (
          <span key={index} className="card-slot">
            <input
              aria-label={`board-${index}`}
              value={card}
              placeholder={index < 3 ? `牌面 ${index + 1}` : "future"}
              onChange={(event) => onUpdateBoard(index, event.target.value)}
            />
            <button
              type="button"
              className="pick-toggle"
              onClick={() => setPickerTarget(pickerTarget === index ? null : index)}
              aria-label={`为 ${index < 3 ? `牌面 ${index + 1}` : `未来牌面 ${index + 1}`} 选牌`}
              aria-pressed={pickerTarget === index}
            >
              选牌
            </button>
          </span>
        ))}
      </div>
      {pickerTarget !== null && (
        <CardPicker
          label={pickerTargetLabel(pickerTarget)}
          usedCards={usedCards}
          onPick={handlePick}
          onClose={() => setPickerTarget(null)}
        />
      )}
    </>
  );
}
