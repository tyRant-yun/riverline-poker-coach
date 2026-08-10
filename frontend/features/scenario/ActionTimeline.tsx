// Action history timeline: clickable replay nodes. Selecting a node moves the
// decision point back/forward; legality is always re-validated by the backend.

import type { ActionEvent } from "../../types/scenario";

type Props = {
  events: ActionEvent[];
  selectedSequence: number;
  onSelectNode: (sequence: number, street: string) => void;
  onRefresh: () => void;
};

export default function ActionTimeline({ events, selectedSequence, onSelectNode, onRefresh }: Props) {
  return (
    <div className="timeline">
      <div className="subheading">
        <span>行动时间线</span>
        <button className="text-button" onClick={onRefresh}>
          重新校验
        </button>
      </div>
      {events.length === 0 ? (
        <p className="muted">尚未录入行动。后端会从盲注和初始筹码推导底池。</p>
      ) : (
        events.map((event) => (
          <button
            className={`timeline-row ${selectedSequence === event.sequence ? "selected" : ""}`}
            key={event.actionId}
            onClick={() => onSelectNode(event.sequence, event.street)}
          >
            <span className="sequence">{String(event.sequence).padStart(2, "0")}</span>
            <span>{event.street}</span>
            <strong>
              Seat {event.actorSeat} · {event.actionType}
            </strong>
            <span className="muted">{event.amount ?? "—"}</span>
          </button>
        ))
      )}
    </div>
  );
}
