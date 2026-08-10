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
}: Props) {
  const [pickerTarget, setPickerTarget] = useState<PickerTarget | null>(null);
  const [heroOnlyMode, setHeroOnlyMode] = useState(false);

  const usedCards = useMemo(
    () => [
      ...scenario.heroHoleCards,
      ...(scenario.villainHoleCards ?? []),
      ...boardInput.filter(Boolean),
    ],
    [scenario.heroHoleCards, scenario.villainHoleCards, boardInput],
  );

  const handlePick = (card: string) => {
    const lower = card.toLowerCase();
    if (pickerTarget === "hero") {
      const current = scenario.heroHoleCards;
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

      <div className="form-grid">
        <label>
          Hero 手牌
          <span className="card-slot">
            <input
              value={scenario.heroHoleCards.join(" ")}
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
        <label>
          Villain 手牌
          <span className="card-slot">
            <input
              value={villainUnknown ? "" : (scenario.villainHoleCards ?? []).join(" ")}
              disabled={villainUnknown}
              placeholder={villainUnknown ? "对手手牌未知（复盘模式）" : undefined}
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
      </div>
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
        复盘模式 · 只填自己的手牌（对手手牌未知）
      </label>
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
            value={scenario.seats[0].startingStack}
            onChange={(event) =>
              onUpdateScenario({
                seats: scenario.seats.map((seat, index) =>
                  index === 0 ? { ...seat, startingStack: Number(event.target.value) || 1 } : seat,
                ),
              })
            }
          />
        </label>
        <label>
          Villain 起始筹码
          <input
            type="number"
            min="1"
            value={scenario.seats[1].startingStack}
            onChange={(event) =>
              onUpdateScenario({
                seats: scenario.seats.map((seat, index) =>
                  index === 1 ? { ...seat, startingStack: Number(event.target.value) || 1 } : seat,
                ),
              })
            }
          />
        </label>
      </div>
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
