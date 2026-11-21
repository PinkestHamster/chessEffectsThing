"""Regression tests for castling classification in highlight-based move tracking."""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PYTHON_DIR = os.path.dirname(_HERE)
if _PYTHON_DIR not in sys.path:
    sys.path.insert(0, _PYTHON_DIR)

from virtual_board import VirtualBoard


def test_queen_move_from_e6_to_g6_does_not_spawn_rook_at_f6():
    board = VirtualBoard()
    board.initialize_from_assigned_teams({"e6": "WHITE"})

    decision = board.process_changed_squares(["e6", "g6"])

    assert decision is not None
    assert decision.kind == "MOVE"
    assert decision.is_capture is False
    assert board.piece_at("g6") == "WHITE"
    assert board.piece_at("f6") is None


def test_kingside_castling_moves_only_the_matching_rook():
    board = VirtualBoard()
    board.initialize_from_assigned_teams({"e1": "WHITE", "h1": "WHITE"})

    decision = board.process_changed_squares(["e1", "g1"])

    assert decision is not None
    assert decision.kind == "CASTLING"
    assert board.piece_at("g1") == "WHITE"
    assert board.piece_at("f1") == "WHITE"
    assert board.piece_at("h1") is None


def test_queenside_castling_moves_only_the_matching_rook():
    board = VirtualBoard()
    board.initialize_from_assigned_teams({"e8": "BLACK", "a8": "BLACK"})

    decision = board.process_changed_squares(["e8", "c8"])

    assert decision is not None
    assert decision.kind == "CASTLING"
    assert board.piece_at("c8") == "BLACK"
    assert board.piece_at("d8") == "BLACK"
    assert board.piece_at("a8") is None


def test_king_move_without_matching_corner_rook_is_not_castling():
    board = VirtualBoard()
    board.initialize_from_assigned_teams({"e1": "WHITE"})

    decision = board.process_changed_squares(["e1", "g1"])

    assert decision is not None
    assert decision.kind == "MOVE"
    assert board.piece_at("f1") is None
    assert board.piece_at("h1") is None


def test_king_move_with_blocked_castling_path_does_not_move_rook():
    board = VirtualBoard()
    board.initialize_from_assigned_teams({
        "e1": "WHITE",
        "f1": "WHITE",
        "h1": "WHITE",
    })

    decision = board.process_changed_squares(["e1", "g1"])

    assert decision is not None
    assert decision.kind == "MOVE"
    assert board.piece_at("f1") == "WHITE"
    assert board.piece_at("h1") == "WHITE"
    assert board.piece_at("g1") == "WHITE"


def test_queen_reaching_back_rank_is_not_classified_as_promotion():
    board = VirtualBoard()
    board.initialize_from_assigned_teams({"d8": "BLACK"})

    decision = board.process_changed_squares(["d8", "d1"])

    assert decision is not None
    assert decision.kind == "MOVE"


def test_pawn_reaching_back_rank_is_classified_as_promotion():
    board = VirtualBoard()
    board.initialize_from_assigned_teams({"a7": "WHITE"})

    decision = board.process_changed_squares(["a7", "a8"])

    assert decision is not None
    assert decision.kind == "PROMOTION"
    assert board._piece_types["a8"] == "queen"


def test_black_pawn_reaching_first_rank_promotes_to_queen():
    board = VirtualBoard()
    board.initialize_from_assigned_teams({"a2": "BLACK"})

    decision = board.process_changed_squares(["a2", "a1"])

    assert decision is not None
    assert decision.kind == "PROMOTION"
    assert board._piece_types["a1"] == "queen"


def test_pawn_capture_on_back_rank_is_a_queen_promotion():
    board = VirtualBoard()
    board.initialize_from_assigned_teams({"b7": "WHITE", "a8": "BLACK"})

    decision = board.process_changed_squares(["b7", "a8"])

    assert decision is not None
    assert decision.kind == "PROMOTION"
    assert decision.is_capture is True
    assert board._piece_types["a8"] == "queen"


def test_same_team_occupied_pair_uses_piece_geometry_to_find_rook_source():
    board = VirtualBoard()
    board.initialize_from_assigned_teams({
        "h1": "WHITE",
        "h3": "WHITE",
        "a7": "BLACK",
    })

    decision = board.process_changed_squares(["h3", "h1"])

    assert decision is not None
    assert decision.source_square == "h1"
    assert decision.destination_square == "h3"
    assert board.piece_at("h1") is None
    assert board.piece_at("h3") == "WHITE"
    assert board._piece_types["h3"] == "rook"


def test_rooks_can_move_up_and_back_without_state_drift_or_false_capture():
    board = VirtualBoard()
    board.initialize_standard()

    moves = [
        (["h2", "h4"], "h2", "h4", "WHITE"),
        (["h7", "h5"], "h7", "h5", "BLACK"),
        (["h1", "h3"], "h1", "h3", "WHITE"),
        (["h8", "h6"], "h8", "h6", "BLACK"),
        (["h3", "h1"], "h3", "h1", "WHITE"),
        (["h6", "h8"], "h6", "h8", "BLACK"),
    ]

    for changed_squares, source, destination, team in moves:
        decision = board.process_changed_squares(changed_squares)
        assert decision is not None
        assert (decision.source_square, decision.destination_square) == (source, destination)
        assert decision.moving_team == team
        assert decision.is_capture is False

    assert board.piece_at("h1") == "WHITE"
    assert board.piece_at("h3") is None
    assert board.piece_at("h8") == "BLACK"
    assert board.piece_at("h6") is None
    assert board.piece_at("h4") == "WHITE"
    assert board.piece_at("h5") == "BLACK"
    assert board.process_changed_squares(["h7", "h6"]) is None
    assert board.piece_at("h7") is None
    assert board.piece_at("h6") is None


def test_wrong_direction_pawn_highlight_does_not_corrupt_board():
    board = VirtualBoard()
    board.initialize_standard()
    board._current_turn = "WHITE"
    board._first_move_after_init = False

    decision = board.process_changed_squares(["h7", "h6"])

    assert decision is None
    assert board.piece_at("h7") == "BLACK"
    assert board.piece_at("h6") is None


def test_unoccupied_highlight_pair_does_not_invent_a_piece_or_capture():
    board = VirtualBoard()
    board.initialize_from_assigned_teams({"a2": "WHITE"})

    decision = board.process_changed_squares(["h8", "h6"])

    assert decision is None
    assert board.piece_at("h8") is None
    assert board.piece_at("h6") is None


def test_same_team_destination_is_reconciled_without_a_false_capture():
    board = VirtualBoard()
    board.initialize_from_assigned_teams({"h1": "WHITE", "h3": "WHITE"})

    decision = board.process_changed_squares(["h1", "h3"])

    assert decision is not None
    assert decision.is_capture is False
    assert board.piece_at("h1") is None
    assert board.piece_at("h3") == "WHITE"
