// Scenario editor: hole cards, blinds, stacks and board input. State lives in
// the workspace; this component only renders and emits patches.

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
          <input
            value={scenario.heroHoleCards.join(" ")}
            onChange={(event) =>
              onUpdateScenario({
                heroHoleCards: event.target.value.split(/\s+/).filter(Boolean).slice(0, 2),
              })
            }
          />
        </label>
        <label>
          Villain 手牌
          <input
            value={(scenario.villainHoleCards ?? []).join(" ")}
            onChange={(event) =>
              onUpdateScenario({
                villainHoleCards: event.target.value.split(/\s+/).filter(Boolean).slice(0, 2),
              })
            }
          />
        </label>
      </div>
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
          <input
            aria-label={`board-${index}`}
            key={index}
            value={card}
            placeholder={index < 3 ? `牌面 ${index + 1}` : "future"}
            onChange={(event) => onUpdateBoard(index, event.target.value)}
          />
        ))}
      </div>
    </>
  );
}
