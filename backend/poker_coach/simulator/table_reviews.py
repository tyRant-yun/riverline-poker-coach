"""Permission-scoped, read-only access to persisted automatic reviews."""
from __future__ import annotations

import sqlite3

from poker_coach.simulator.auto_review import AutomaticReviewV1


class TableReviewReader:
    def __init__(self, path: str):
        self._connection = sqlite3.connect(path)
        self._connection.row_factory = sqlite3.Row

    def close(self) -> None:
        self._connection.close()

    def list(self, session_id: str, hero_seat: int) -> list[AutomaticReviewV1]:
        rows = self._connection.execute("SELECT payload_json FROM automatic_reviews WHERE session_id = ? AND hero_seat = ? ORDER BY hand_id DESC", (session_id, hero_seat)).fetchall()
        return [AutomaticReviewV1.model_validate_json(row["payload_json"]) for row in rows]

    def get(self, session_id: str, hand_id: str, hero_seat: int) -> AutomaticReviewV1 | None:
        row = self._connection.execute("SELECT payload_json FROM automatic_reviews WHERE session_id = ? AND hand_id = ? AND hero_seat = ?", (session_id, hand_id, hero_seat)).fetchone()
        return None if row is None else AutomaticReviewV1.model_validate_json(row["payload_json"])


def public_review(review: AutomaticReviewV1) -> dict[str, object]:
    return {"handId": review.hand_id, "heroSeat": review.hero_seat, "completionSequence": review.completion_sequence,
            "heroDecisions": [node.to_dict() for node in review.hero_decisions], "references": review.references.to_dict(), "fingerprint": review.fingerprint}
