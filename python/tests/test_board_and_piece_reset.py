"""Tests for separating board finding ([ key) from piece position reset (R key)."""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PYTHON_DIR = os.path.dirname(_HERE)
if _PYTHON_DIR not in sys.path:
    sys.path.insert(0, _PYTHON_DIR)

import backend


class MockWriter:
    def __init__(self):
        self.sent = []
        self.acked = []

    def send(self, msg):
        self.sent.append(msg)

    def ack(self, cmd_id):
        self.acked.append(cmd_id)


def test_reset_pieces_without_locked_board_errors():
    original_writer = backend.writer
    original_rect = backend.board_tracker.rect
    mock_writer = MockWriter()
    backend.writer = mock_writer
    backend.board_tracker.rect = None

    try:
        backend.handle_reset_pieces({"commandId": "cmd-1"})
        assert any(m.get("type") == "error" and m.get("code") == "NO_BOARD_LOCKED" for m in mock_writer.sent)
        assert "cmd-1" in mock_writer.acked
    finally:
        backend.writer = original_writer
        backend.board_tracker.rect = original_rect


def test_reset_pieces_with_locked_board_initializes_standard():
    original_writer = backend.writer
    original_rect = backend.board_tracker.rect
    original_orientation = backend.board_tracker.orientation
    mock_writer = MockWriter()
    backend.writer = mock_writer
    backend.board_tracker.rect = (100, 100, 400, 400)
    backend.board_tracker.orientation = "white_bottom"
    backend.virtual_board.reset()

    try:
        backend.handle_reset_pieces({"commandId": "cmd-2"})
        assert "cmd-2" in mock_writer.acked
        # Verify 32 pieces established
        assert backend.virtual_board.piece_at("e1") == "WHITE"
        assert backend.virtual_board.piece_at("e8") == "BLACK"
        assert backend.virtual_board.piece_at("e4") is None
        assert len(backend.virtual_board._pieces) == 32
        assert any(m.get("type") == "state_change" and m.get("state") == "BOARD_LOCKED" for m in mock_writer.sent)
    finally:
        backend.writer = original_writer
        backend.board_tracker.rect = original_rect
        backend.board_tracker.orientation = original_orientation
