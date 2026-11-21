"""Pixel-scanner tests for exact board colors, selection, and move verification."""

import os
import sys
import numpy as np
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PYTHON_DIR = os.path.dirname(_HERE)
if _PYTHON_DIR not in sys.path:
    sys.path.insert(0, _PYTHON_DIR)

from board_tracker import BoardTracker
from highlight_detector import HighlightDetector
from virtual_board import VirtualBoard
from pixel_scanner import (
    PixelScanner,
    HL_LIGHT_RGB,
    HL_DARK_RGB,
    LIGHT_SQ_RGB,
    DARK_SQ_RGB,
    CHECK_LIGHT_RGB,
    CHECK_DARK_RGB,
    TARGET_LIGHT_RGB,
    TARGET_DARK_RGB,
    HL_LIGHT_BGR,
    HL_DARK_BGR,
    LIGHT_SQ_BGR,
    DARK_SQ_BGR,
    CHECK_LIGHT_BGR,
    CHECK_DARK_BGR,
    TARGET_LIGHT_BGR,
    TARGET_DARK_BGR,
    SQUARE_COLORS_RGB,
)


def test_ten_target_colors():
    # 1. Highlighted light square: #EEAEB6 (238, 174, 182)
    assert np.allclose(HL_LIGHT_RGB, [238, 174, 182])
    # 2. Highlighted dark square:  #EC9BA8 (236, 155, 168)
    assert np.allclose(HL_DARK_RGB, [236, 155, 168])
    # 3. Light square:             #FEFFFE (254, 255, 254)
    assert np.allclose(LIGHT_SQ_RGB, [254, 255, 254])
    # 4. Dark square:              #FBD9E1 (251, 217, 225)
    assert np.allclose(DARK_SQ_RGB, [251, 217, 225])
    # 5. Checked king on light square: #F19299 (241, 146, 153)
    assert np.allclose(CHECK_LIGHT_RGB, [241, 146, 153])
    # 6. Checked king on dark square:  #EF818C (239, 129, 140)
    assert np.allclose(CHECK_DARK_RGB, [239, 129, 140])
    # 7. Capturable target on light square: #DADBDA (218, 219, 218)
    assert np.allclose(TARGET_LIGHT_RGB, [218, 219, 218])
    # 8. Capturable target on dark square:  #CC959C (204, 149, 156)
    assert np.allclose(TARGET_DARK_RGB, [204, 149, 156])
    assert SQUARE_COLORS_RGB["capturable_target_highlight_light"] is None
    assert SQUARE_COLORS_RGB["capturable_target_highlight_dark"] is None
    assert len(SQUARE_COLORS_RGB) == 10


def test_custom_square_palette_is_used_for_classification():
    scanner = PixelScanner()
    palette = {
        "move_highlight_light": [10, 20, 30],
        "move_highlight_dark": [11, 21, 31],
        "normal_light": [40, 50, 60],
        "normal_dark": [41, 51, 61],
        "checked_king_light": [70, 80, 90],
        "checked_king_dark": [71, 81, 91],
        "capturable_target_light": [100, 110, 120],
        "capturable_target_dark": [101, 111, 121],
        "capturable_target_highlight_light": [130, 140, 150],
        "capturable_target_highlight_dark": [131, 141, 151],
    }

    scanner.set_palette(palette)

    assert scanner.classify_square(np.array([10, 20, 30]), is_light=True) == "HIGHLIGHT"
    assert scanner.classify_square(np.array([41, 51, 61]), is_light=False) == "NORMAL"
    assert scanner.classify_square(np.array([70, 80, 90]), is_light=True) == "CHECK"
    assert scanner.classify_square(np.array([101, 111, 121]), is_light=False) == "TARGET"
    assert scanner.classify_square(np.array([130, 140, 150]), is_light=True) == "TARGET"


def test_saved_grey_theme_classifies_move_highlights():
    scanner = PixelScanner()
    scanner.set_palette({
        "move_highlight_light": [190, 200, 206],
        "move_highlight_dark": [166, 176, 182],
        "normal_light": [216, 217, 216],
        "normal_dark": [168, 169, 168],
        "checked_king_light": [224, 129, 136],
        "checked_king_dark": [202, 107, 114],
        "capturable_target_light": [163, 172, 177],
        "capturable_target_dark": [144, 145, 144],
        "capturable_target_highlight_light": [163, 172, 177],
        "capturable_target_highlight_dark": [143, 151, 156],
    })

    assert scanner.classify_square(np.array([190, 200, 206]), is_light=True) == "HIGHLIGHT"
    assert scanner.classify_square(np.array([166, 176, 182]), is_light=False) == "HIGHLIGHT"


def test_custom_square_palette_rejects_missing_colors():
    scanner = PixelScanner()

    with pytest.raises(ValueError, match="all ten"):
        scanner.set_palette({"move_highlight_light": [1, 2, 3]})


def test_pixel_scanner_initialization():
    bt = BoardTracker()
    frame = np.zeros((1000, 1000, 3), dtype=np.uint8)
    for row in range(8):
        for col in range(8):
            is_light = (col + row) % 2 == 0
            color_bgr = LIGHT_SQ_BGR if is_light else DARK_SQ_BGR
            y1, y2 = 100 + row * 100, 100 + (row + 1) * 100
            x1, x2 = 100 + col * 100, 100 + (col + 1) * 100
            frame[y1:y2, x1:x2] = color_bgr.astype(np.uint8)

    bt.lock_board((100, 100, 800, 800), current_frame=frame, orientation="white_bottom")
    scanner = PixelScanner(bt)
    ok = scanner.initialize(bt, frame)

    assert ok is True
    assert len(scanner._sample_targets) == 64
    assert len(scanner.baseline_rgb) == 64


def test_highlight_calibration_uses_final_black_bottom_square_names():
    tracker = BoardTracker()
    frame = np.zeros((1000, 1000, 3), dtype=np.uint8)
    for row in range(8):
        for col in range(8):
            color = LIGHT_SQ_BGR if (col + row) % 2 == 0 else DARK_SQ_BGR
            frame[100 + row * 100 : 200 + row * 100, 100 + col * 100 : 200 + col * 100] = color.astype(np.uint8)

    tracker.lock_board((100, 100, 800, 800), current_frame=frame, orientation="white_bottom")
    detector = HighlightDetector(tracker)
    for col in (0, 1):
        square = tracker.squares[f"{chr(ord('a') + col)}8"]
        color = HL_LIGHT_BGR if (square.col + square.row) % 2 == 0 else HL_DARK_BGR
        x, y, width, height = square.bounds
        frame[y : y + height, x : x + width] = color.astype(np.uint8)

    assert detector.calibrate(frame)
    assert set(detector._last_highlighted) == {"a8", "b8"}

    tracker.set_orientation("black_bottom")
    assert detector.calibrate(frame)
    assert set(detector._last_highlighted) == {"h1", "g1"}


def test_black_bottom_moves_are_detected_and_mapped_to_algebraic_squares():
    tracker = BoardTracker()
    frame = np.zeros((1000, 1000, 3), dtype=np.uint8)
    for row in range(8):
        for col in range(8):
            color = LIGHT_SQ_BGR if (col + row) % 2 == 0 else DARK_SQ_BGR
            frame[100 + row * 100 : 200 + row * 100, 100 + col * 100 : 200 + col * 100] = color.astype(np.uint8)

    tracker.lock_board((100, 100, 800, 800), current_frame=frame, orientation="black_bottom")
    stale_square = tracker.squares["h8"]
    stale_is_light = (stale_square.col + stale_square.row) % 2 == 0
    stale_color = HL_LIGHT_BGR if stale_is_light else HL_DARK_BGR
    stale_x, stale_y, stale_width, stale_height = stale_square.bounds
    startup_artifact = stale_color + np.array([15, 0, 0], dtype=np.float32)
    frame[stale_y : stale_y + stale_height, stale_x : stale_x + stale_width] = startup_artifact.astype(np.uint8)

    scanner = PixelScanner(tracker)
    assert scanner.initialize(tracker, frame)
    assert scanner._initial_highlighted == {"h8"}
    board = VirtualBoard()
    assigned_teams = {}
    for file_name in "abcdefgh":
        assigned_teams[f"{file_name}1"] = "WHITE"
        assigned_teams[f"{file_name}2"] = "WHITE"
        assigned_teams[f"{file_name}7"] = "BLACK"
        assigned_teams[f"{file_name}8"] = "BLACK"
    board.initialize_from_assigned_teams(assigned_teams, "BLACK")

    def paint_square(square_name, highlighted):
        square = tracker.squares[square_name]
        is_light = (square.col + square.row) % 2 == 0
        color = (HL_LIGHT_BGR if is_light else HL_DARK_BGR) if highlighted else (
            LIGHT_SQ_BGR if is_light else DARK_SQ_BGR
        )
        x, y, width, height = square.bounds
        frame[y : y + height, x : x + width] = color.astype(np.uint8)

    paint_square("e2", True)
    paint_square("e4", True)
    detected = scanner.scan_frame(frame)
    assert detected is not None and set(detected) == {"e2", "e4"}
    assert scanner.last_square_status["e2"] == "HL"
    assert scanner.last_square_status["e4"] == "HL"
    assert set(scanner.last_scan_raw_highlights) == {"h8", "e2", "e4"}
    assert scanner._initial_highlighted == {"h8"}
    decision = board.process_changed_squares(detected)
    assert decision is not None
    assert (decision.source_square, decision.destination_square) == ("e2", "e4")
    assert decision.moving_team == "WHITE"
    scanner.set_last_move(decision.source_square, decision.destination_square)

    paint_square("e2", False)
    paint_square("e4", False)
    paint_square("e7", True)
    paint_square("e5", True)
    detected = scanner.scan_frame(frame)
    assert detected is not None and set(detected) == {"e7", "e5"}
    assert set(scanner.last_scan_raw_highlights) == {"h8", "e7", "e5"}
    assert scanner._initial_highlighted == {"h8"}
    decision = board.process_changed_squares(detected)
    assert decision is not None
    assert (decision.source_square, decision.destination_square) == ("e7", "e5")
    assert decision.moving_team == "BLACK"

    paint_square("e7", False)
    paint_square("e5", False)
    paint_square("d8", True)
    assert scanner.scan_frame(frame) is None
    assert set(scanner.last_scan_raw_highlights) == {"h8", "d8"}
    assert scanner.last_scan_highlights == ["d8"]

    paint_square("e8", True)
    detected = scanner.scan_frame(frame)
    assert detected is not None and set(detected) == {"d8", "e8"}
    assert set(scanner.last_scan_raw_highlights) == {"h8", "d8", "e8"}
    assert scanner._initial_highlighted == {"h8"}

    paint_square("d8", False)
    paint_square("e8", False)
    paint_square("h8", True)
    paint_square("h6", True)
    detected = scanner.scan_frame(frame)
    assert detected is not None and set(detected) == {"h8", "h6"}
    assert "h8" not in scanner._initial_highlighted


def test_black_bottom_h2_move_after_rook_capture_is_detected():
    tracker = BoardTracker()
    frame = np.zeros((1000, 1000, 3), dtype=np.uint8)
    for row in range(8):
        for col in range(8):
            color = LIGHT_SQ_BGR if (col + row) % 2 == 0 else DARK_SQ_BGR
            frame[100 + row * 100 : 200 + row * 100, 100 + col * 100 : 200 + col * 100] = color.astype(np.uint8)

    tracker.lock_board((100, 100, 800, 800), current_frame=frame, orientation="black_bottom")
    h8 = tracker.squares["h8"]
    h8_color = HL_LIGHT_BGR if (h8.col + h8.row) % 2 == 0 else HL_DARK_BGR
    x, y, width, height = h8.bounds
    startup_artifact = h8_color + np.array([15, 0, 0], dtype=np.float32)
    frame[y : y + height, x : x + width] = startup_artifact.astype(np.uint8)

    scanner = PixelScanner(tracker)
    assert scanner.initialize(tracker, frame)
    board = VirtualBoard()
    board.initialize_standard("BLACK")

    def paint_square(square_name, highlighted):
        square = tracker.squares[square_name]
        is_light = (square.col + square.row) % 2 == 0
        color = (HL_LIGHT_BGR if is_light else HL_DARK_BGR) if highlighted else (
            LIGHT_SQ_BGR if is_light else DARK_SQ_BGR
        )
        sx, sy, sw, sh = square.bounds
        frame[sy : sy + sh, sx : sx + sw] = color.astype(np.uint8)

    def play_move(source, destination):
        paint_square(source, True)
        paint_square(destination, True)
        detected = scanner.scan_frame(frame)
        assert detected is not None and set(detected) == {source, destination}
        decision = board.process_changed_squares(detected)
        assert decision is not None
        assert (decision.source_square, decision.destination_square) == (source, destination)
        scanner.set_last_move(source, destination)
        paint_square(source, False)
        paint_square(destination, False)

    for source, destination in (
        ("e2", "e4"),
        ("a7", "a5"),
        ("g2", "g4"),
        ("c7", "c5"),
        ("a2", "a4"),
        ("a8", "a6"),
        ("a1", "a3"),
        ("h7", "h5"),
        ("g4", "h5"),
        ("h8", "h5"),
        ("h2", "h4"),
        ("b7", "b5"),
        ("h1", "h3"),
    ):
        play_move(source, destination)


def test_move_highlight_uses_only_top_right_corner_at_resized_board():
    board_size = 537
    frame = np.zeros((board_size + 80, board_size + 80, 3), dtype=np.uint8)
    board_x = board_y = 40
    square_size = board_size / 8
    for row in range(8):
        for col in range(8):
            x1 = round(board_x + col * square_size)
            x2 = round(board_x + (col + 1) * square_size)
            y1 = round(board_y + row * square_size)
            y2 = round(board_y + (row + 1) * square_size)
            color = LIGHT_SQ_BGR if (row + col) % 2 == 0 else DARK_SQ_BGR
            frame[y1:y2, x1:x2] = color.astype(np.uint8)

    tracker = BoardTracker()
    tracker.lock_board(
        (board_x, board_y, board_size, board_size),
        current_frame=frame,
        orientation="black_bottom",
    )
    scanner = PixelScanner(tracker)
    assert scanner.initialize(tracker, frame)

    for square_name in ("h2", "h4"):
        square = tracker.squares[square_name]
        is_light = (square.col + square.row) % 2 == 0
        highlight = HL_LIGHT_BGR if is_light else HL_DARK_BGR
        x, y, width, height = square.bounds
        frame[y : y + height, x : x + width] = highlight.astype(np.uint8)
        y1, y2, x1, x2 = scanner._sample_regions[square_name]
        assert x1 > x + width // 2
        assert y1 < y + height // 2
        normal = LIGHT_SQ_BGR if is_light else DARK_SQ_BGR
        frame[y1:y2, x1:x2] = normal.astype(np.uint8)

    assert scanner.scan_frame(frame) is None
    for square_name in ("h2", "h4"):
        square = tracker.squares[square_name]
        is_light = (square.col + square.row) % 2 == 0
        highlight = HL_LIGHT_BGR if is_light else HL_DARK_BGR
        y1, y2, x1, x2 = scanner._sample_regions[square_name]
        frame[y1:y2, x1:x2] = highlight.astype(np.uint8)

    detected = scanner.scan_frame(frame)
    assert detected is not None and set(detected) == {"h2", "h4"}
    scanner.scan_frame(frame)
    scanner.scan_frame(frame)
    assert scanner.last_square_status["h2"] in ("HL", "HD")

    h2 = tracker.squares["h2"]
    is_light = (h2.col + h2.row) % 2 == 0
    normal = LIGHT_SQ_BGR if is_light else DARK_SQ_BGR
    hx, hy, hw, hh = h2.bounds
    frame[hy : hy + hh, hx : hx + hw] = normal.astype(np.uint8)
    scanner.scan_frame(frame)
    scanner.scan_frame(frame)
    assert scanner.last_square_status["h2"] in ("HL", "HD")


@pytest.mark.parametrize("board_size", [501, 537])
def test_move_scanning_scales_with_detected_board_size(board_size):
    frame = np.zeros((board_size + 80, board_size + 80, 3), dtype=np.uint8)
    board_x = board_y = 40
    square_size = board_size / 8
    light = np.array([216, 217, 216], dtype=np.uint8)
    dark = np.array([168, 169, 168], dtype=np.uint8)
    for row in range(8):
        for col in range(8):
            x1 = round(board_x + col * square_size)
            x2 = round(board_x + (col + 1) * square_size)
            y1 = round(board_y + row * square_size)
            y2 = round(board_y + (row + 1) * square_size)
            frame[y1:y2, x1:x2] = light if (row + col) % 2 == 0 else dark

    tracker = BoardTracker()
    tracker.lock_board(
        (board_x, board_y, board_size, board_size),
        current_frame=frame,
        orientation="white_bottom",
    )
    scanner = PixelScanner(tracker)
    scanner.set_palette({
        "move_highlight_light": [190, 200, 206],
        "move_highlight_dark": [166, 176, 182],
        "normal_light": [216, 217, 216],
        "normal_dark": [168, 169, 168],
        "checked_king_light": [224, 129, 136],
        "checked_king_dark": [202, 107, 114],
        "capturable_target_light": [163, 172, 177],
        "capturable_target_dark": [144, 145, 144],
        "capturable_target_highlight_light": [163, 172, 177],
        "capturable_target_highlight_dark": [143, 151, 156],
    })
    assert scanner.initialize(tracker, frame)
    expected_sample_size = max(3, int(round((board_size / 8) * 0.05)))
    assert scanner._sample_targets[0][2] - scanner._sample_targets[0][1] == expected_sample_size

    for name in ("e2", "e4"):
        square = tracker.squares[name]
        is_light = (square.col + square.row) % 2 == 0
        x, y, width, height = square.bounds
        highlight = (206, 200, 190) if is_light else (182, 176, 166)
        frame[y:y + height, x:x + width] = highlight

    assert set(scanner.scan_frame(frame) or []) == {"e2", "e4"}


def test_selection_vs_real_movement():
    bt = BoardTracker()
    frame = np.zeros((1000, 1000, 3), dtype=np.uint8)
    for row in range(8):
        for col in range(8):
            is_light = (col + row) % 2 == 0
            color_bgr = LIGHT_SQ_BGR if is_light else DARK_SQ_BGR
            y1, y2 = 100 + row * 100, 100 + (row + 1) * 100
            x1, x2 = 100 + col * 100, 100 + (col + 1) * 100
            frame[y1:y2, x1:x2] = color_bgr.astype(np.uint8)

    bt.lock_board((100, 100, 800, 800), current_frame=frame, orientation="white_bottom")
    scanner = PixelScanner(bt)
    scanner.initialize(bt, frame)

    vb = VirtualBoard()
    vb.initialize_standard("WHITE")

    def paint_square(sq_name, highlighted: bool):
        sq = bt.squares[sq_name]
        is_l = (sq.col + sq.row) % 2 == 0
        if highlighted:
            color = HL_LIGHT_BGR if is_l else HL_DARK_BGR
        else:
            color = LIGHT_SQ_BGR if is_l else DARK_SQ_BGR
        x, y, w, h = sq.bounds
        frame[y : y + h, x : x + w] = color.astype(np.uint8)

    # 1. Piece selection at start: user selects e2 (only 1 square highlighted)
    paint_square("e2", highlighted=True)
    assert scanner.scan_frame(frame) is None, "Selection of 1 piece must NOT trigger movement"

    # User deselects e2
    paint_square("e2", highlighted=False)
    assert scanner.scan_frame(frame) is None

    # 2. Real Move 1: e2 -> e4 (2 squares change to highlight at the same time)
    paint_square("e2", highlighted=True)
    paint_square("e4", highlighted=True)
    move1 = scanner.scan_frame(frame)
    assert move1 is not None, "Real move must be detected"
    assert set(move1) == {"e2", "e4"}
    vb.process_changed_squares(move1)
    assert vb.piece_at("e2") is None
    assert vb.piece_at("e4") == "WHITE"

    # Repeated frame must return None
    assert scanner.scan_frame(frame) is None

    # 3. User selects e7 (previous move e2, e4 STILL highlighted, now e7 also highlighted = 3 squares!)
    paint_square("e7", highlighted=True)
    assert scanner.scan_frame(frame) is None, "Piece selection while old move highlighted must NOT trigger move"

    # User changes selection to c7
    paint_square("e7", highlighted=False)
    paint_square("c7", highlighted=True)
    assert scanner.scan_frame(frame) is None, "Selection change must NOT trigger move"

    # 4. User completes real Move 2: c7 -> c5
    # e2 and e4 UNHIGHLIGHT!
    paint_square("e2", highlighted=False)
    paint_square("e4", highlighted=False)
    # c7 and c5 are HIGHLIGHTED!
    paint_square("c7", highlighted=True)
    paint_square("c5", highlighted=True)

    move2 = scanner.scan_frame(frame)
    assert move2 is not None, "Real move must be detected when old squares unhighlight and 2 new squares highlight"
    assert set(move2) == {"c7", "c5"}
    vb.process_changed_squares(move2)
    assert vb.piece_at("c7") is None
    assert vb.piece_at("c5") == "BLACK"

    # 5. Capture move: White plays d2 -> d4, Black selects c5
    paint_square("c7", highlighted=False)
    paint_square("c5", highlighted=False)
    paint_square("d2", highlighted=True)
    paint_square("d4", highlighted=True)
    move3 = scanner.scan_frame(frame)
    assert set(move3) == {"d2", "d4"}
    vb.process_changed_squares(move3)

    # Black selects c5 to capture (d2, d4 still highlighted + c5 highlighted = 3 squares)
    paint_square("c5", highlighted=True)
    assert scanner.scan_frame(frame) is None, "Capture piece selection must NOT trigger move"

    # Black captures d4: c5xd4!
    # d2 unhighlights, c5 and d4 are highlighted!
    paint_square("d2", highlighted=False)
    paint_square("c5", highlighted=True)
    paint_square("d4", highlighted=True)

    move4 = scanner.scan_frame(frame)
    assert move4 is not None
    assert set(move4) == {"c5", "d4"}
    dec4 = vb.process_changed_squares(move4)
    assert dec4.is_capture is True
    assert vb.piece_at("c5") is None
    assert vb.piece_at("d4") == "BLACK"
    assert vb.piece_counts()["WHITE"] == 15


def test_selection_with_capture_target_ignored():
    """
    Direct test for the user's reported bug:
    e2 -> e4, Black plays f7 -> f5.
    White selects e4 (pawn that can capture f5).
    Chess.com displays capture hint overlay on f5 (altering its color away from highlight),
    while f7 remains highlighted from Black's move.
    Total highlighted squares: exactly 2 (e4 and f7).
    Both PixelScanner and VirtualBoard must reject this as a move.
    When White captures e4 x f5, f7 unhighlights and {e4, f5} must be recognized as capture.
    """
    bt = BoardTracker()
    frame = np.zeros((1000, 1000, 3), dtype=np.uint8)
    for row in range(8):
        for col in range(8):
            is_light = (col + row) % 2 == 0
            color_bgr = LIGHT_SQ_BGR if is_light else DARK_SQ_BGR
            y1, y2 = 100 + row * 100, 100 + (row + 1) * 100
            x1, x2 = 100 + col * 100, 100 + (col + 1) * 100
            frame[y1:y2, x1:x2] = color_bgr.astype(np.uint8)

    bt.lock_board((100, 100, 800, 800), current_frame=frame, orientation="white_bottom")
    scanner = PixelScanner(bt)
    scanner.initialize(bt, frame)

    vb = VirtualBoard()
    vb.initialize_standard("WHITE")

    def paint_square(sq_name, highlighted: bool):
        sq = bt.squares[sq_name]
        is_l = (sq.col + sq.row) % 2 == 0
        color = (HL_LIGHT_BGR if is_l else HL_DARK_BGR) if highlighted else (LIGHT_SQ_BGR if is_l else DARK_SQ_BGR)
        x, y, w, h = sq.bounds
        frame[y : y + h, x : x + w] = color.astype(np.uint8)

    # 1. White plays e2 -> e4
    paint_square("e2", True)
    paint_square("e4", True)
    m1 = scanner.scan_frame(frame)
    assert m1 is not None and set(m1) == {"e2", "e4"}
    d1 = vb.process_changed_squares(m1)
    assert d1 is not None
    scanner.set_last_move(d1.source_square, d1.destination_square)

    # 2. Black plays f7 -> f5
    paint_square("e2", False)
    paint_square("e4", False)
    paint_square("f7", True)
    paint_square("f5", True)
    m2 = scanner.scan_frame(frame)
    assert m2 is not None and set(m2) == {"f7", "f5"}
    d2 = vb.process_changed_squares(m2)
    assert d2 is not None
    scanner.set_last_move(d2.source_square, d2.destination_square)

    # 3. White selects e4:
    # - e4 is highlighted (selected)
    # - f5 displays a capturable-target overlay
    # - f7 remains highlighted from Black's previous move
    paint_square("e4", True)
    sq_f5 = bt.squares["f5"]
    x, y, w, h = sq_f5.bounds
    frame[y : y + h, x : x + w] = TARGET_LIGHT_BGR.astype(np.uint8)

    # Scanner MUST reject {e4, f7} because f5 is a TARGET.
    assert scanner.scan_frame(frame) is None
    # VirtualBoard MUST reject {e4, f7}
    assert vb.process_changed_squares(["e4", "f7"]) is None

    # 4. White plays e4 x f5 (capture)
    # f7 unhighlights, e4 and f5 are highlighted
    paint_square("f7", False)
    paint_square("e4", True)
    paint_square("f5", True)

    m3 = scanner.scan_frame(frame)
    assert m3 is not None and set(m3) == {"e4", "f5"}
    d3 = vb.process_changed_squares(m3)
    assert d3 is not None
    assert d3.is_capture is True
    assert d3.source_square == "e4"
    assert d3.destination_square == "f5"
    assert vb.piece_at("e4") is None
    assert vb.piece_at("f5") == "WHITE"
    assert vb.piece_counts()["BLACK"] == 15


def test_selecting_f5_after_e7_e6_is_not_a_move():
    """A target on e6 must suppress the stale e7 highlight after f5 is selected."""
    bt = BoardTracker()
    frame = np.zeros((1000, 1000, 3), dtype=np.uint8)
    for row in range(8):
        for col in range(8):
            color = LIGHT_SQ_BGR if (col + row) % 2 == 0 else DARK_SQ_BGR
            frame[100 + row * 100 : 200 + row * 100, 100 + col * 100 : 200 + col * 100] = color.astype(np.uint8)

    bt.lock_board((100, 100, 800, 800), current_frame=frame, orientation="white_bottom")
    scanner = PixelScanner(bt)
    scanner.initialize(bt, frame)
    board = VirtualBoard()
    board.initialize_standard("WHITE")

    def paint_square(square_name, color):
        square = bt.squares[square_name]
        x, y, width, height = square.bounds
        frame[y : y + height, x : x + width] = color.astype(np.uint8)

    def paint_highlight(square_name):
        square = bt.squares[square_name]
        is_light = (square.col + square.row) % 2 == 0
        paint_square(square_name, HL_LIGHT_BGR if is_light else HL_DARK_BGR)

    def paint_normal(square_name):
        square = bt.squares[square_name]
        is_light = (square.col + square.row) % 2 == 0
        paint_square(square_name, LIGHT_SQ_BGR if is_light else DARK_SQ_BGR)

    last_highlights = set()

    def play_move(source, destination):
        nonlocal last_highlights
        for square in last_highlights:
            paint_normal(square)
        paint_highlight(source)
        paint_highlight(destination)
        detected = scanner.scan_frame(frame)
        assert detected is not None and set(detected) == {source, destination}
        decision = board.process_changed_squares(detected)
        assert decision is not None
        scanner.set_last_move(decision.source_square, decision.destination_square)
        last_highlights = {source, destination}

    # Reach a position with White's pawn on f5, then Black moves e7 to e6.
    play_move("f2", "f4")
    play_move("a7", "a6")
    play_move("f4", "f5")
    play_move("e7", "e6")

    # Selecting f5 makes f5/e7 look like a legal knight move. Either target
    # shade on e6 must suppress the selection frame.
    paint_highlight("f5")
    e6_is_light = (bt.squares["e6"].col + bt.squares["e6"].row) % 2 == 0
    target_color = TARGET_LIGHT_BGR if e6_is_light else TARGET_DARK_BGR
    target_y1, target_y2, target_x1, target_x2 = scanner._sample_regions["e6"]
    frame[target_y1:target_y2, target_x1:target_x2] = target_color.astype(np.uint8)
    assert scanner._is_capturable_target_sample(
        np.median(frame[target_y1:target_y2, target_x1:target_x2], axis=(0, 1))[::-1],
        e6_is_light,
    )
    assert scanner.scan_frame(frame) is None

    # The actual capture changes the scanned pair to f5/e6 and clears e7.
    paint_normal("e7")
    paint_highlight("e6")
    actual_move = scanner.scan_frame(frame)
    assert actual_move is not None and set(actual_move) == {"f5", "e6"}
    capture = board.process_changed_squares(actual_move)
    assert capture is not None
    assert (capture.source_square, capture.destination_square) == ("f5", "e6")
    assert capture.is_capture is True


def test_move_can_land_on_previous_source_square():
    """A later move may legally use the prior move's origin as its destination."""
    bt = BoardTracker()
    frame = np.zeros((1000, 1000, 3), dtype=np.uint8)
    for row in range(8):
        for col in range(8):
            is_light = (col + row) % 2 == 0
            color_bgr = LIGHT_SQ_BGR if is_light else DARK_SQ_BGR
            y1, y2 = 100 + row * 100, 100 + (row + 1) * 100
            x1, x2 = 100 + col * 100, 100 + (col + 1) * 100
            frame[y1:y2, x1:x2] = color_bgr.astype(np.uint8)

    bt.lock_board((100, 100, 800, 800), current_frame=frame, orientation="white_bottom")
    scanner = PixelScanner(bt)
    scanner.initialize(bt, frame)

    def paint_square(sq_name, highlighted):
        sq = bt.squares[sq_name]
        is_light = (sq.col + sq.row) % 2 == 0
        color = (HL_LIGHT_BGR if is_light else HL_DARK_BGR) if highlighted else (LIGHT_SQ_BGR if is_light else DARK_SQ_BGR)
        x, y, w, h = sq.bounds
        frame[y : y + h, x : x + w] = color.astype(np.uint8)

    # White moves e2 -> e4, leaving those two squares highlighted.
    paint_square("e2", True)
    paint_square("e4", True)
    assert set(scanner.scan_frame(frame) or []) == {"e2", "e4"}
    scanner.set_last_move("e2", "e4")

    # Black then moves e7 -> e2. The destination is the previous source and
    # must be accepted, rather than mistaken for a stale highlight.
    paint_square("e4", False)
    paint_square("e7", True)
    paint_square("e2", True)
    move = scanner.scan_frame(frame)
    assert move is not None
    assert set(move) == {"e7", "e2"}


def test_capture_selection_marker_around_piece_does_not_trigger_move():
    """A capture marker around the target piece must suppress selection-only highlights."""
    bt = BoardTracker()
    frame = np.zeros((1000, 1000, 3), dtype=np.uint8)
    for row in range(8):
        for col in range(8):
            is_light = (col + row) % 2 == 0
            color = LIGHT_SQ_BGR if is_light else DARK_SQ_BGR
            frame[100 + row * 100 : 200 + row * 100, 100 + col * 100 : 200 + col * 100] = color.astype(np.uint8)

    bt.lock_board((100, 100, 800, 800), current_frame=frame, orientation="white_bottom")
    scanner = PixelScanner(bt)
    palette = {
        name: color.tolist() if color is not None else None
        for name, color in SQUARE_COLORS_RGB.items()
    }
    palette["capturable_target_highlight_light"] = [180, 140, 150]
    palette["capturable_target_highlight_dark"] = [170, 130, 140]
    scanner.set_palette(palette)
    scanner.initialize(bt, frame)
    scanner.set_last_move("e7", "e6")

    def paint_square(square_name, color):
        square = bt.squares[square_name]
        x, y, width, height = square.bounds
        frame[y : y + height, x : x + width] = color.astype(np.uint8)

    # Selecting f5 while e6 remains highlighted can resemble the f5-e6
    # capture pair. The exact highlighted-target color identifies selection.
    paint_square("e7", LIGHT_SQ_BGR)
    paint_square("e6", HL_LIGHT_BGR if (bt.squares["e6"].col + bt.squares["e6"].row) % 2 == 0 else HL_DARK_BGR)
    paint_square("f5", HL_LIGHT_BGR if (bt.squares["f5"].col + bt.squares["f5"].row) % 2 == 0 else HL_DARK_BGR)
    is_light = (bt.squares["e6"].col + bt.squares["e6"].row) % 2 == 0
    target = [180, 140, 150] if is_light else [170, 130, 140]
    target_y1, target_y2, target_x1, target_x2 = scanner._sample_regions["e6"]
    frame[target_y1:target_y2, target_x1:target_x2] = np.asarray(target[::-1], dtype=np.uint8)
    assert scanner.scan_frame(frame) is None

    # Once the user completes the capture, the target marker disappears while
    # the move-highlight pair remains on f5/e6 and is accepted.
    highlight = HL_LIGHT_BGR if is_light else HL_DARK_BGR
    frame[target_y1:target_y2, target_x1:target_x2] = highlight.astype(np.uint8)
    detected = scanner.scan_frame(frame)
    assert detected is not None
    assert set(detected) == {"f5", "e6"}


def test_checked_king_color_distinction():
    """
    Verify that a checked king (#F19299 / #EF818C) is classified as 'CHECK'
    and NOT misclassified as a move highlight, allowing moves that deliver check to be recognized.
    """
    bt = BoardTracker()
    frame = np.zeros((1000, 1000, 3), dtype=np.uint8)
    for row in range(8):
        for col in range(8):
            is_light = (col + row) % 2 == 0
            color_bgr = LIGHT_SQ_BGR if is_light else DARK_SQ_BGR
            y1, y2 = 100 + row * 100, 100 + (row + 1) * 100
            x1, x2 = 100 + col * 100, 100 + (col + 1) * 100
            frame[y1:y2, x1:x2] = color_bgr.astype(np.uint8)

    bt.lock_board((100, 100, 800, 800), current_frame=frame, orientation="white_bottom")
    scanner = PixelScanner(bt)
    scanner.initialize(bt, frame)

    # Check color classifications directly
    assert scanner.classify_square(CHECK_LIGHT_RGB, is_light=True) == "CHECK"
    assert scanner.classify_square(CHECK_DARK_RGB, is_light=False) == "CHECK"
    assert scanner.classify_square(TARGET_LIGHT_RGB, is_light=True) == "TARGET"
    assert scanner.classify_square(TARGET_DARK_RGB, is_light=False) == "TARGET"
    assert scanner.classify_square(HL_LIGHT_RGB, is_light=True) == "HIGHLIGHT"
    assert scanner.classify_square(HL_DARK_RGB, is_light=False) == "HIGHLIGHT"
    assert scanner.classify_square(LIGHT_SQ_RGB, is_light=True) == "NORMAL"
    assert scanner.classify_square(DARK_SQ_RGB, is_light=False) == "NORMAL"

    # Move e2 -> e4 that delivers check: king on e8 turns into check color
    def paint(sq_name, kind):
        sq = bt.squares[sq_name]
        is_l = (sq.col + sq.row) % 2 == 0
        if kind == "HL":
            bgr = HL_LIGHT_BGR if is_l else HL_DARK_BGR
        elif kind == "CHECK":
            bgr = CHECK_LIGHT_BGR if is_l else CHECK_DARK_BGR
        x, y, w, h = sq.bounds
        frame[y : y + h, x : x + w] = bgr.astype(np.uint8)

    paint("e2", "HL")
    paint("e4", "HL")
    paint("e8", "CHECK")  # King in check!

    # Move must still be detected as exactly 2 squares ['e2', 'e4'] because e8 is CHECK, not HIGHLIGHT
    m = scanner.scan_frame(frame)
    assert m is not None
    assert set(m) == {"e2", "e4"}
