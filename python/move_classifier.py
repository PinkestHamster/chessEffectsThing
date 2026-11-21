"""Conservative Phase 4 move and capture inference."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import time
import uuid
from typing import Any, Dict, Iterable, Optional


def _rank(square: str) -> int:
    return int(square[1])


def _file(square: str) -> int:
    return ord(square[0]) - ord("a")


@dataclass
class MoveDecision:
    source_square: str
    destination_square: str
    captured_square: Optional[str]
    is_capture: bool
    kind: str
    confidence: float
    decision_reason: str
    source: str
    moving_team: str = "UNKNOWN"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sourceSquare": self.source_square,
            "destinationSquare": self.destination_square,
            "capturedSquare": self.captured_square,
            "isCapture": self.is_capture,
            "kind": self.kind,
            "confidence": round(self.confidence, 3),
            "decisionReason": self.decision_reason,
            "source": self.source,
            "movingTeam": self.moving_team,
        }

    def capture_event(self, timestamp: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if not self.is_capture:
            return None
        return {
            "eventId": str(uuid.uuid4()),
            "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
            "sourceSquare": self.source_square,
            "destinationSquare": self.destination_square,
            "capturedSquare": self.captured_square,
            "capturingTeam": self.moving_team,
            "movingTeam": self.moving_team,
            "confidence": round(self.confidence, 3),
            "decisionReason": self.decision_reason,
        }


class MoveClassifier:
    """Compares stable occupancy snapshots and emits one conservative decision."""

    def __init__(self, duplicate_window_sec: float = 1.0) -> None:
        self._baseline: Dict[str, Dict[str, Any]] = {}
        self._last_signature = ""
        self._last_emit_at = 0.0
        self.duplicate_window_sec = duplicate_window_sec
        self.local_team = "WHITE"
        self._teams: Dict[str, str] = {}

    def reset(self, clear_position: bool = True) -> None:
        self._baseline = {}
        self._last_signature = ""
        self._last_emit_at = 0.0
        if clear_position:
            self._teams = {}

    def initialize_standard_position(self, local_team: str) -> None:
        self.reset(clear_position=True)
        self.local_team = local_team
        for file_name in "abcdefgh":
            self._teams[f"{file_name}1"] = "WHITE"
            self._teams[f"{file_name}2"] = "WHITE"
            self._teams[f"{file_name}7"] = "BLACK"
            self._teams[f"{file_name}8"] = "BLACK"

    def initialize_from_scan(self, observations: Dict[str, Any], local_team: str) -> None:
        """Trust the current board image as-is; no assumption about game phase."""
        self.reset(clear_position=True)
        self.local_team = local_team
        self._baseline = {name: self._snapshot(obs) for name, obs in observations.items()}
        for square, observation in observations.items():
            if observation.status == "OCCUPIED" and observation.color in ("WHITE", "BLACK"):
                self._teams[square] = observation.color

    def initialize_starting_rows(self, squares: Iterable[Any], observations: Dict[str, Any], lower_team: str) -> None:
        """Initialize the guaranteed 16-versus-16 opening layout from board geometry."""
        self.reset(clear_position=True)
        self.local_team = lower_team
        self._baseline = {name: self._snapshot(obs) for name, obs in observations.items()}
        for square in squares:
            if square.row <= 1:
                self._teams[square.name] = "BLACK" if lower_team == "WHITE" else "WHITE"
            elif square.row >= 6:
                self._teams[square.name] = lower_team

    def initialize_from_assigned_teams(self, assigned_teams: Dict[str, str], observations: Dict[str, Any], local_team: str) -> None:
        """Initialize the board state from explicit team assignments (e.g. 16 vs 16 halves)."""
        self.reset(clear_position=True)
        self.local_team = local_team
        self._baseline = {name: self._snapshot(obs) for name, obs in observations.items()}
        for square, team in assigned_teams.items():
            if team in ("WHITE", "BLACK"):
                self._teams[square] = team

    def team_at(self, square: str) -> str:
        return self._teams.get(square, "NONE")

    def is_local_piece(self, square: str) -> bool:
        return self.team_at(square) == self.local_team

    def board_state(self) -> Dict[str, str]:
        return dict(self._teams)

    def piece_counts(self) -> Dict[str, int]:
        return {"WHITE": sum(team == "WHITE" for team in self._teams.values()), "BLACK": sum(team == "BLACK" for team in self._teams.values())}

    def process(
        self,
        observations: Dict[str, Any],
    ) -> Optional[MoveDecision]:
        """Process a frame's observations."""
        if not observations:
            return None

        current = {name: self._snapshot(obs) for name, obs in observations.items()}
        if not self._baseline:
            self._baseline = current
            # Do NOT auto-populate _teams from visual color – it is unreliable.
            # _teams is ONLY set by initialize_from_assigned_teams() on R press.
            return None

        # If no R press yet, _teams is empty – just keep baseline fresh, no moves possible
        if not self._teams:
            self._baseline = current
            return None

        # Compare visual state against known _teams positions
        changed = [
            s for s in current
            if (current[s]["status"] == "OCCUPIED") != (s in self._teams)
            or (s in self._teams and current[s]["status"] == "OCCUPIED"
                and current[s]["color"] in ("WHITE", "BLACK")
                and current[s]["color"] != self._teams[s])
        ]

        if not changed:
            return None

        # Check stability of the changed candidate squares
        changed_obs = [observations[s] for s in changed if s in observations]
        if changed_obs and not all(obs.is_stable for obs in changed_obs):
            return None

        decision = self._classify(current, changed)
        if decision is None:
            return None

        signature = f"{decision.source_square}>{decision.destination_square}:{decision.captured_square or ''}"
        now = time.monotonic()
        if signature == self._last_signature and now - self._last_emit_at < self.duplicate_window_sec:
            return None
        self._last_signature, self._last_emit_at = signature, now
        self._apply_decision(decision)
        self._baseline = current
        return decision

    def _apply_decision(self, decision: MoveDecision) -> None:
        team = self._teams.pop(decision.source_square, decision.moving_team)
        if decision.captured_square:
            self._teams.pop(decision.captured_square, None)
        if team in ("WHITE", "BLACK"):
            self._teams[decision.destination_square] = team
        if decision.kind == "CASTLING" and _file(decision.destination_square) in (2, 6):
            rank = decision.destination_square[1]
            rook_source, rook_destination = ("a" + rank, "d" + rank) if _file(decision.destination_square) == 2 else ("h" + rank, "f" + rank)
            rook_team = self._teams.pop(rook_source, team)
            if rook_team in ("WHITE", "BLACK"):
                self._teams[rook_destination] = rook_team

    @staticmethod
    def _snapshot(obs: Any) -> Dict[str, Any]:
        return {
            "status": obs.status,
            "color": obs.color,
            "confidence": float(obs.confidence),
            "signature": tuple(getattr(obs, "appearance", ())),
        }

    @staticmethod
    def _changed(before: Dict[str, Any], after: Dict[str, Any]) -> bool:
        if before["status"] != after["status"] or before["color"] != after["color"]:
            return True
        a, b = before["signature"], after["signature"]
        if len(a) == len(b) and a:
            return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5 >= 12.0
        return False

    def _classify(
        self,
        current: Dict[str, Dict[str, Any]],
        changed: Iterable[str],
    ) -> Optional[MoveDecision]:
        changed = list(changed)
        if self._teams:
            emptied = [s for s in changed if s in self._teams and current[s]["status"] == "EMPTY"]
            filled = [s for s in changed if s not in self._teams and current[s]["status"] == "OCCUPIED"]
            replaced = [s for s in changed if s in self._teams and current[s]["status"] == "OCCUPIED" and current[s]["color"] != self._teams[s]]
        else:
            emptied = [s for s in changed if self._baseline[s]["status"] == "OCCUPIED" and current[s]["status"] == "EMPTY"]
            filled = [s for s in changed if self._baseline[s]["status"] == "EMPTY" and current[s]["status"] == "OCCUPIED"]
            replaced = [s for s in changed if self._baseline[s]["status"] == "OCCUPIED" and current[s]["status"] == "OCCUPIED"]

        source, destination = self._resolve_move(emptied, filled + replaced)
        if not source or not destination:
            return None

        confidence = min(current[source]["confidence"], current[destination]["confidence"])
        was_occupied = (destination in self._teams) if self._teams else (self._baseline[destination]["status"] == "OCCUPIED")
        moving_team = self.team_at(source)

        # Castling has two origins and two destinations on one rank. It is never a capture.
        if len(emptied) == 2 and len(filled) == 2 and not replaced and len({_rank(s) for s in emptied + filled}) == 1:
            return MoveDecision(source, destination, None, False, "CASTLING", confidence, "Stable dual-piece transition classified as castling", "visual_only", moving_team)

        # En passant: the destination was empty and another adjacent square disappears.
        extra = [s for s in emptied if s != source]
        en_passant = next((s for s in extra if _rank(s) == _rank(source) and _file(s) == _file(destination)), None)
        if en_passant and (destination not in self._teams if self._teams else self._baseline[destination]["status"] == "EMPTY"):
            return MoveDecision(source, destination, en_passant, True, "EN_PASSANT", confidence, "Stable source, destination, and en-passant victim transition", "visual_only", moving_team)

        kind = "PROMOTION" if _rank(destination) in (1, 8) else "MOVE"
        if was_occupied:
            target_team = self.team_at(destination)
            if moving_team != "NONE" and target_team == moving_team:
                return None
            return MoveDecision(source, destination, destination, True, kind, confidence, "Stable source-empty and occupied destination replacement", "visual_only", moving_team)
        return MoveDecision(source, destination, None, False, kind, confidence, "Stable source-empty and destination-filled transition", "visual_only", moving_team)

    @staticmethod
    def _resolve_move(emptied: list[str], destinations: list[str]) -> tuple[Optional[str], Optional[str]]:
        if len(emptied) == 1 and len(destinations) == 1:
            return emptied[0], destinations[0]
        if len(emptied) == 2 and len(destinations) == 1:
            destination = destinations[0]
            source = next((s for s in emptied if _rank(s) != _rank(destination)), None)
            return source, destination
        # In castling, use the king-like (two-square) motion only to provide useful debug data.
        for source in emptied:
            for destination in destinations:
                if _rank(source) == _rank(destination) and abs(_file(source) - _file(destination)) == 2:
                    return source, destination
        return None, None
