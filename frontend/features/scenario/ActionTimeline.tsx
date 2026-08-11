// Action history timeline: selecting a player action asks the workspace to
// derive its action-before decision projection; legality stays backend-owned.

import type { ActionEvent } from "../../types/scenario";
import { isPlayerAction } from "../../lib/poker/handReview";

type Props = {
  events: ActionEvent[];
  selectedActionId: string | null;
  onSelectAction: (actionId: string) => void;
  onRefresh: () => void;
};

export default function ActionTimeline({ events, selectedActionId, onSelectAction, onRefresh }: Props) {
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
        events.map((event) => {
          const playerAction = isPlayerAction(event);
          const contents = (
            <>
              <span className="sequence">{String(event.sequence).padStart(2, "0")}</span>
              <span>{event.street}</span>
              <strong>
                Seat {event.actorSeat} · {event.actionType}
              </strong>
              <span className="muted">{event.amount ?? "—"}</span>
            </>
          );
          if (!playerAction) {
            return (
              <div className="timeline-row timeline-row--deal" key={event.actionId} aria-label={`状态事件 ${event.actionType}`} aria-disabled="true">
                {contents}
              </div>
            );
          }
          return (
            <button
              className={`timeline-row ${selectedActionId === event.actionId ? "selected" : ""}`}
              key={event.actionId}
              id={`action-timeline-${event.actionId}`}
              onClick={() => onSelectAction(event.actionId)}
            >
              {contents}
            </button>
          );
        })
      )}
    </div>
  );
}
