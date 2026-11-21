"""
VirtualBoard – internal simulated chess board tracking piece state and resolving highlight moves.
Blindly follows visual highlights without illegal move checks.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Set, Tuple
from move_classifier import MoveDecision, _file, _rank

log = logging.getLogger(__name__)


def _standard_piece_type(square: str) -> Optional[str]:
    if len(square) != 2:
        return None
    file_name, rank = square[0], square[1]
    if rank in ("2", "7"):
        return "pawn"
    if rank not in ("1", "8"):
        return None
    return {
        "a": "rook",
        "b": "knight",
        "c": "bishop",
        "d": "queen",
        "e": "king",
        "f": "bishop",
        "g": "knight",
        "h": "rook",
    }.get(file_name)


def _piece_can_move_geometry(
    piece_type: Optional[str],
    source: str,
    destination: str,
    team: str,
    is_capture: bool = False,
) -> bool:
    df = abs(_file(destination) - _file(source))
    rank_delta = _rank(destination) - _rank(source)
    dr = abs(rank_delta)
    if piece_type == "rook":
        return (df == 0) != (dr == 0)
    if piece_type == "bishop":
        return df == dr and df > 0
    if piece_type == "queen":
        return (df == 0) != (dr == 0) or (df == dr and df > 0)
    if piece_type == "knight":
        return (df, dr) in ((1, 2), (2, 1))
    if piece_type == "king":
        return max(df, dr) == 1 or (df == 2 and dr == 0)
    if piece_type == "pawn":
        forward = 1 if team == "WHITE" else -1
        if is_capture:
            return df == 1 and rank_delta == forward
        if df == 0 and rank_delta == forward:
            return True
        start_rank = 2 if team == "WHITE" else 7
        return df == 0 and _rank(source) == start_rank and rank_delta == 2 * forward
    return False


def is_valid_chess_geometry(sq1: str, sq2: str) -> bool:
    """Check if two squares form a valid geometric chess move (orthogonal, diagonal, or knight leap)."""
    if sq1 == sq2 or len(sq1) != 2 or len(sq2) != 2:
        return False
    f1, r1 = ord(sq1[0]) - ord("a"), int(sq1[1])
    f2, r2 = ord(sq2[0]) - ord("a"), int(sq2[1])
    df = abs(f2 - f1)
    dr = abs(r2 - r1)
    if (df == 0 and dr > 0) or (dr == 0 and df > 0):
        return True
    if df == dr and df > 0:
        return True
    if (df == 1 and dr == 2) or (df == 2 and dr == 1):
        return True
    return False


class VirtualBoard:
    """Maintains simulated chess board state driven by highlight detection."""

    def __init__(self, local_team: str = "WHITE") -> None:
        self.local_team: str = local_team
        self._pieces: Dict[str, str] = {}
        self._piece_types: Dict[str, str] = {}
        self._current_turn: str = "WHITE"
        self._last_highlighted: Set[str] = set()
        self._last_move: Optional[Tuple[str, str]] = None
        self._first_move_after_init: bool = True

    def reset(self) -> None:
        self._pieces = {}
        self._piece_types = {}
        self._current_turn = "WHITE"
        self._last_highlighted = set()
        self._last_move = None
        self._first_move_after_init = True

    def initialize_standard(self, local_team: str = "WHITE") -> None:
        """Initialize standard 32-piece chess position."""
        self.reset()
        self.local_team = local_team
        for file_char in "abcdefgh":
            self._pieces[f"{file_char}1"] = "WHITE"
            self._pieces[f"{file_char}2"] = "WHITE"
            self._pieces[f"{file_char}7"] = "BLACK"
            self._pieces[f"{file_char}8"] = "BLACK"
            for rank in "1278":
                square = f"{file_char}{rank}"
                piece_type = _standard_piece_type(square)
                if piece_type:
                    self._piece_types[square] = piece_type
        self._current_turn = "WHITE"
        log.info("VirtualBoard initialized standard position. Local team: %s", local_team)

    def initialize_from_assigned_teams(self, assigned_teams: Dict[str, str], local_team: str = "WHITE") -> None:
        """Initialize from explicit square->team mapping (e.g. from R press 16+16 split)."""
        self.reset()
        self.local_team = local_team
        for sq, team in assigned_teams.items():
            if team in ("WHITE", "BLACK"):
                self._pieces[sq] = team
                piece_type = _standard_piece_type(sq)
                if piece_type:
                    self._piece_types[sq] = piece_type
        self._current_turn = "WHITE"
        log.info("VirtualBoard initialized with %d pieces. Local team: %s", len(self._pieces), local_team)

    def set_last_highlighted(self, squares: Iterable[str]) -> None:
        self._last_highlighted = set(squares)

    def piece_at(self, square: str) -> Optional[str]:
        return self._pieces.get(square)

    def is_local_piece(self, square: str) -> bool:
        return self._pieces.get(square) == self.local_team

    def board_state(self) -> Dict[str, str]:
        return dict(self._pieces)

    def piece_counts(self) -> Dict[str, int]:
        white = sum(1 for t in self._pieces.values() if t == "WHITE")
        black = sum(1 for t in self._pieces.values() if t == "BLACK")
        return {"WHITE": white, "BLACK": black}

    def process_changed_squares(
        self,
        changed_squares: List[str],
    ) -> Optional[MoveDecision]:
        """
        When exactly 2 squares are detected as changed, resolve the move and update the internal board.
        Strictly uses the internal board state to identify source/destination and detect captures.
        """
        if len(changed_squares) != 2:
            return None

        sq1, sq2 = changed_squares[0], changed_squares[1]
        if not is_valid_chess_geometry(sq1, sq2):
            log.warning("Invalid chess geometry between %s and %s", sq1, sq2)
            return None

        current_set = {sq1, sq2}
        if current_set == self._last_highlighted:
            return None

        occ1 = self._pieces.get(sq1)
        occ2 = self._pieces.get(sq2)

        # 1. Identify source and destination squares from the internal board state
        if occ1 and not occ2:
            source, destination = sq1, sq2
            moving_team = occ1
        elif occ2 and not occ1:
            source, destination = sq2, sq1
            moving_team = occ2
        elif occ1 and occ2:
            # Both occupied: capture move
            if occ1 == self._current_turn and occ2 != self._current_turn:
                source, destination = sq1, sq2
                moving_team = occ1
            elif occ2 == self._current_turn and occ1 != self._current_turn:
                source, destination = sq2, sq1
                moving_team = occ2
            elif occ1 != occ2:
                if self._current_turn == "WHITE" and occ1 == "WHITE":
                    source, destination = sq1, sq2
                    moving_team = occ1
                elif self._current_turn == "BLACK" and occ1 == "BLACK":
                    source, destination = sq1, sq2
                    moving_team = occ1
                else:
                    source, destination = sq2, sq1
                    moving_team = occ2
            else:
                possible_sources = [
                    (sq1, sq2, occ1),
                    (sq2, sq1, occ2),
                ]
                typed_sources = [
                    candidate
                    for candidate in possible_sources
                    if _piece_can_move_geometry(
                        self._piece_types.get(candidate[0]),
                        candidate[0],
                        candidate[1],
                        candidate[2],
                        occ1 != occ2,
                    )
                ]
                if len(typed_sources) == 1:
                    source, destination, moving_team = typed_sources[0]
                else:
                    log.warning(
                        "Ambiguous same-team move rejected: %s (%s) and %s (%s), turn=%s",
                        sq1,
                        self._piece_types.get(sq1, "unknown"),
                        sq2,
                        self._piece_types.get(sq2, "unknown"),
                        self._current_turn,
                    )
                    return None
        else:
            log.warning("Move rejected: neither highlighted square is occupied: %s, %s", sq1, sq2)
            return None

        if not source or not destination:
            return None

        if not is_valid_chess_geometry(source, destination):
            return None

        if not self._first_move_after_init and moving_team != self._current_turn:
            log.warning(
                "Move rejected: %s tried to move %s -> %s on %s's turn",
                moving_team,
                source,
                destination,
                self._current_turn,
            )
            return None

        # 2. Check whether destination square is occupied in the internal board state
        captured_piece = self._pieces.get(destination)
        is_capture = captured_piece is not None and captured_piece != moving_team

        moving_piece_type = self._piece_types.get(source)
        castle_rank = _rank(source)
        castle_rook_file = "h" if _file(destination) == 6 else "a"
        castle_rook_source = f"{castle_rook_file}{castle_rank}"
        castle_path = (
            (f"f{castle_rank}", f"g{castle_rank}")
            if castle_rook_file == "h"
            else (f"b{castle_rank}", f"c{castle_rank}", f"d{castle_rank}")
        )
        is_castling = (
            moving_piece_type == "king"
            and source in ("e1", "e8")
            and destination in ("c1", "g1", "c8", "g8")
            and castle_rank == _rank(destination)
            and not is_capture
            and self._piece_types.get(castle_rook_source) == "rook"
            and self._pieces.get(castle_rook_source) == moving_team
            and all(square not in self._pieces for square in castle_path)
        )
        if moving_piece_type and not is_castling and not _piece_can_move_geometry(
            moving_piece_type,
            source,
            destination,
            moving_team,
            is_capture,
        ):
            log.warning(
                "Move rejected: %s cannot move %s -> %s (team=%s, capture=%s)",
                moving_piece_type,
                source,
                destination,
                moving_team,
                is_capture,
            )
            return None

        if self._first_move_after_init:
            self._current_turn = moving_team
            self._first_move_after_init = False

        # 3. If occupied, immediately print a capture message
        # 4. Otherwise, process as normal move
        if is_capture:
            print(f"[CAPTURE] {moving_team} on {source} captured {captured_piece} on {destination}!", flush=True)
            log.info("[CAPTURE] %s on %s captured %s on %s", moving_team, source, captured_piece, destination)
        else:
            log.info("[MOVE] %s moved %s to %s", moving_team, source, destination)

        # Classify move kind
        kind = "MOVE"
        is_promotion = (
            moving_piece_type == "pawn"
            and _rank(destination) == (8 if moving_team == "WHITE" else 1)
        )
        if is_castling:
            kind = "CASTLING"
        elif is_promotion:
            kind = "PROMOTION"
        elif is_capture:
            kind = "CAPTURE"

        captured_square = destination if is_capture else None
        decision = MoveDecision(
            source_square=source,
            destination_square=destination,
            captured_square=captured_square,
            is_capture=is_capture,
            kind=kind,
            confidence=1.0,
            decision_reason=f"Pixel scan move: {source} -> {destination}",
            source="visual_only",
            moving_team=moving_team or self._current_turn,
        )

        # 5. Move source piece to destination square in internal board state
        # 6. Mark source square as empty
        self._apply_move(source, destination, decision.moving_team, kind)
        self._last_highlighted = current_set
        self._last_move = (source, destination)
        return decision

    def process_highlights(
        self,
        highlighted_squares: List[str],
    ) -> Optional[MoveDecision]:
        """Backward-compatible alias for process_changed_squares."""
        return self.process_changed_squares(highlighted_squares)

    def _apply_move(self, source: str, destination: str, moving_team: str, kind: str) -> None:
        team = moving_team or self._pieces.pop(source, self._current_turn)
        self._pieces.pop(source, None)
        moving_piece_type = self._piece_types.pop(source, None)
        self._piece_types.pop(destination, None)
        self._pieces[destination] = team
        if moving_piece_type:
            self._piece_types[destination] = "queen" if kind == "PROMOTION" else moving_piece_type
        self._current_turn = "BLACK" if team == "WHITE" else "WHITE"

        # Handle castling rook movement
        if kind == "CASTLING":
            rank = destination[1]
            if _file(destination) == 6:  # Kingside
                rook_from, rook_to = f"h{rank}", f"f{rank}"
            else:  # Queenside
                rook_from, rook_to = f"a{rank}", f"d{rank}"
            rook_team = self._pieces.get(rook_from)
            if rook_team == team and self._piece_types.get(rook_from) == "rook":
                self._pieces.pop(rook_from)
                self._piece_types.pop(rook_from, None)
                self._pieces[rook_to] = rook_team
                self._piece_types[rook_to] = "rook"
                log.info("Castling rook moved: %s -> %s", rook_from, rook_to)
