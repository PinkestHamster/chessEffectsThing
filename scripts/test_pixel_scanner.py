"""
Test script for 4 target colors and selection vs real movement verification.
"""
import sys
import os
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))

from board_tracker import BoardTracker
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
)


def run_tests():
    print("=== Testing All 8 Target Colors & Movement Recognition ===")

    # 1. Colors
    assert np.allclose(HL_LIGHT_RGB, [238, 174, 182])
    assert np.allclose(HL_DARK_RGB, [236, 155, 168])
    assert np.allclose(LIGHT_SQ_RGB, [254, 255, 254])
    assert np.allclose(DARK_SQ_RGB, [251, 217, 225])
    assert np.allclose(CHECK_LIGHT_RGB, [241, 146, 153])
    assert np.allclose(CHECK_DARK_RGB, [239, 129, 140])
    assert np.allclose(TARGET_LIGHT_RGB, [218, 219, 218])
    assert np.allclose(TARGET_DARK_RGB, [204, 149, 156])
    print("[PASS] All 8 Exact Target Colors verified:")
    print("       1. Highlighted light square:           #EEAEB6 (238, 174, 182)")
    print("       2. Highlighted dark square:            #EC9BA8 (236, 155, 168)")
    print("       3. Light square:                       #FEFFFE (254, 255, 254)")
    print("       4. Dark square:                        #FBD9E1 (251, 217, 225)")
    print("       5. Checked king on light square:       #F19299 (241, 146, 153)")
    print("       6. Checked king on dark square:        #EF818C (239, 129, 140)")
    print("       7. Capturable target on light square:  #DADBDA (218, 219, 218)")
    print("       8. Capturable target on dark square:   #CC959C (204, 149, 156)")

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
        frame[y + 4 : y + 20, x + 4 : x + 20] = color.astype(np.uint8)

    # Test selection (1 square)
    paint_square("e2", True)
    assert scanner.scan_frame(frame) is None
    print("[PASS] Piece selection (1 square) correctly ignored")

    # Real move 1: e2 -> e4
    paint_square("e4", True)
    m1 = scanner.scan_frame(frame)
    assert m1 is not None and set(m1) == {"e2", "e4"}
    d1 = vb.process_changed_squares(m1)
    assert d1 is not None
    scanner.set_last_move(d1.source_square, d1.destination_square)
    print(f"[PASS] Real move 1 detected: {m1} ({d1.source_square} -> {d1.destination_square})")

    # Real move 2: Black plays f7 -> f5
    paint_square("e2", False)
    paint_square("e4", False)
    paint_square("f7", True)
    paint_square("f5", True)
    m2 = scanner.scan_frame(frame)
    assert m2 is not None and set(m2) == {"f7", "f5"}
    d2 = vb.process_changed_squares(m2)
    assert d2 is not None
    scanner.set_last_move(d2.source_square, d2.destination_square)
    print(f"[PASS] Real move 2 detected: {m2} ({d2.source_square} -> {d2.destination_square})")

    # CRITICAL BUG SCENARIO: White clicks e4 to select pawn!
    # - e4 is highlighted (selection)
    # - f5 has a capture hint ring (custom color, not among the 4 highlight colors)
    # - f7 is STILL highlighted from Black's previous move!
    paint_square("e4", True)
    # Paint f5 with the exact capturable target dark square color #CC959C
    sq_f5 = bt.squares["f5"]
    x, y, w, h = sq_f5.bounds
    frame[y + 4 : y + 20, x + 4 : x + 20] = TARGET_DARK_BGR.astype(np.uint8)

    # Frame now has exactly 2 squares with highlight colors: e4 and f7!
    # PixelScanner MUST reject this because f7 is _old_source!
    m_sel = scanner.scan_frame(frame)
    assert m_sel is None, "Selection of e4 with capture hint on f5 and lingering f7 highlight MUST return None"
    # VirtualBoard MUST also reject [e4, f7] due to impossible chess geometry
    assert vb.process_changed_squares(["e4", "f7"]) is None
    print("[PASS] CRITICAL BUG SCENARIO: Selection of e4 with captureable f5 correctly ignored by both scanner and virtual board!")

    # White executes the real capture: e4 x f5!
    # f7 unhighlights, e4 and f5 are both normal highlight colors
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
    assert d3.captured_square == "f5"
    scanner.set_last_move(d3.source_square, d3.destination_square)
    print(f"[PASS] Real capture e4 x f5 correctly detected: {m3} (captured on {d3.captured_square})")

    print("\nALL VERIFICATION TESTS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    run_tests()
