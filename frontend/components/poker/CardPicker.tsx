// 52-card picker: click a card to hand it to the caller. Cards already used
// elsewhere in the scenario (hole cards, board) are disabled so the same
// physical card cannot appear twice. Keyboard input on the text boxes
// remains fully supported alongside this picker.

const RANKS = ["A", "K", "Q", "J", "T", "9", "8", "7", "6", "5", "4", "3", "2"];

const SUITS: { symbol: string; suit: string; cls: string }[] = [
  { symbol: "♠", suit: "s", cls: "black" },
  { symbol: "♥", suit: "h", cls: "red" },
  { symbol: "♦", suit: "d", cls: "red" },
  { symbol: "♣", suit: "c", cls: "black" },
];

type Props = {
  label: string;
  usedCards: string[];
  onPick: (card: string) => void;
  onClose: () => void;
};

export default function CardPicker({ label, usedCards, onPick, onClose }: Props) {
  const used = new Set(usedCards.map((card) => card.toLowerCase()));
  return (
    <div className="card-picker" role="group" aria-label={`选牌器 ${label}`}>
      <div className="card-picker__head">
        <span className="card-picker__label">正在为 {label} 选牌</span>
        <button className="text-button" onClick={onClose} aria-label="关闭选牌器">
          关闭
        </button>
      </div>
      <div className="card-picker__grid">
        {SUITS.map(({ symbol, suit, cls }) => (
          <div key={suit} className="card-picker__row">
            {RANKS.map((rank) => {
              const card = `${rank}${suit}`;
              const taken = used.has(card.toLowerCase());
              return (
                <button
                  key={card}
                  type="button"
                  className={`pick-card ${cls}`}
                  disabled={taken}
                  onClick={() => onPick(card)}
                  aria-label={`选牌 ${card}`}
                >
                  <span className="pick-card__rank">{rank}</span>
                  <span className="pick-card__suit">{symbol}</span>
                </button>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
