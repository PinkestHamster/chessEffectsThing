#!/usr/bin/env python3
"""
Chess Vision FX – Python Backend
Phase 1: Screen capture and project foundation.

Communication protocol:
  stdin  ← Electron sends line-delimited JSON commands
  stdout → Python sends line-delimited JSON messages
  stderr → Diagnostic logs only (never parsed by Electron)

This module is the process entry point. It wires together:
  - The IPC reader/writer (protocol.py)
  - Screen capture (capture.py)
  - Command dispatcher
"""

import sys
import os
import time
import threading
import signal
import logging
import numpy as np

# Configure logging to stderr ONLY – stdout is reserved for the protocol.
logging.basicConfig(
    stream=sys.stderr,
    level=logging.DEBUG,
    format="[%(levelname)s %(module)s] %(message)s",
)
log = logging.getLogger(__name__)

# Add the python directory to sys.path so sibling modules resolve correctly.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from protocol import MessageWriter, read_commands
from capture import ScreenCapturer
from board_detector import BoardDetector, BoardCandidate
from board_tracker import BoardTracker
from occupancy_detector import SquareOccupancyDetector
from highlight_detector import HighlightDetector
from virtual_board import VirtualBoard
from pixel_scanner import PixelScanner

# ─── Version ──────────────────────────────────────────────────────────────────
VERSION = "0.5.0"

# ─── Global objects ───────────────────────────────────────────────────────────
writer = MessageWriter(sys.stdout)
capturer: ScreenCapturer | None = None
board_detector = BoardDetector()
board_tracker = BoardTracker()
occupancy_detector = SquareOccupancyDetector(board_tracker)
highlight_detector = HighlightDetector(board_tracker)
virtual_board = VirtualBoard()
pixel_scanner = PixelScanner(board_tracker)
cached_candidates: list[BoardCandidate] = []
_shutdown_event = threading.Event()
_debug_mode = False


_last_debug_emit = 0.0


def _send_board_debug(final_action: str = "", standard_piece_setup: bool = False) -> None:
    """Single overlay payload: trusted team labels, live real-time occupied squares, counts, and output."""
    active_board = virtual_board.board_state()
    counts = virtual_board.piece_counts()
    team = virtual_board.local_team

    writer.send({
        "type": "board_debug",
        "squares": active_board,
        "realtimeOccupied": active_board,
        "pieceCounts": counts,
        "localTeam": team,
        "thinking": "Watching the board",
        "finalAction": final_action,
        "pieceTypeSetup": "standard" if standard_piece_setup else None,
    })


def _on_move_detected(changed_squares: list[str], timestamp: str, frame: np.ndarray | None = None) -> None:
    """Ultra-fast movement processing driven entirely by pixel changes."""
    decision = virtual_board.process_changed_squares(changed_squares)
    if decision is not None:
        pixel_scanner.last_rejected_pair = None
        pixel_scanner.set_last_move(decision.source_square, decision.destination_square)
        team = decision.moving_team.title() if decision.moving_team in ("WHITE", "BLACK") else "A piece"
        action = f"{team} moved {decision.source_square} to {decision.destination_square}"
        if decision.is_capture:
            action += f" and captured on {decision.captured_square}"

        # Send move decision
        writer.send({"type": "move_decision", **decision.to_dict()})

        # Send capture event if capture
        if decision.is_capture:
            event = decision.capture_event(timestamp)
            if event:
                writer.send({"type": "capture_event", **event})

        # Update debug display immediately
        _send_board_debug(final_action=action)
    elif _debug_mode:
        pixel_scanner.last_rejected_pair = list(changed_squares)
        log.warning(
            "Move scan detected %s but board rejected it (orientation=%s, local_team=%s)",
            changed_squares,
            board_tracker.orientation,
            virtual_board.local_team,
        )
    # The scanner has already recorded this visual highlight pair. Keep it
    # consumed even when the board model rejects it; rolling back would emit
    # the same stale/selection pair on every captured frame.


def _on_occupancy_frame(observations, timestamp: str, frame: np.ndarray | None = None) -> None:
    """Frame callback: routes changed squares to immediate move processing."""
    if isinstance(observations, list):
        _on_move_detected(observations, timestamp, frame)


# ─── Command handlers ─────────────────────────────────────────────────────────

def handle_get_monitors(cmd: dict) -> None:
    monitors = ScreenCapturer.list_monitors()
    writer.send({"type": "monitor_list", "monitors": monitors})
    writer.ack(cmd["commandId"])


def handle_start_capture(cmd: dict) -> None:
    global capturer

    if capturer and capturer.is_running():
        capturer.stop()

    monitor_index = int(cmd.get("monitorIndex", 0))
    fps           = float(cmd.get("fps", 5))
    send_previews = bool(cmd.get("sendPreviews", True))

    monitors = ScreenCapturer.list_monitors()
    if 0 <= monitor_index < len(monitors):
        mon = monitors[monitor_index]
        board_tracker.set_monitor_offset((mon["left"], mon["top"]), mon["scale"])

    capturer = ScreenCapturer(
        monitor_index=monitor_index,
        target_fps=fps,
        send_previews=send_previews,
        writer=writer,
        debug=_debug_mode,
    )
    capturer.set_tracker(board_tracker)
    capturer.set_occupancy_detector(occupancy_detector)
    capturer.set_highlight_detector(highlight_detector)
    capturer.set_pixel_scanner(pixel_scanner)
    capturer.set_move_callback(_on_move_detected)
    capturer.start()
    writer.ack(cmd["commandId"])
    log.info("Capture started on monitor %d @ %.1f fps", monitor_index, fps)


def handle_stop_capture(cmd: dict) -> None:
    global capturer
    if capturer:
        capturer.stop()
        capturer = None
    writer.ack(cmd["commandId"])
    log.info("Capture stopped")


def handle_set_monitor(cmd: dict) -> None:
    """Change monitor mid-stream."""
    global capturer
    if capturer and capturer.is_running():
        fps = capturer.target_fps
        send_previews = capturer.send_previews
        capturer.stop()
        capturer = ScreenCapturer(
            monitor_index=int(cmd.get("monitorIndex", 0)),
            target_fps=fps,
            send_previews=send_previews,
            writer=writer,
            debug=_debug_mode,
        )
        capturer.set_tracker(board_tracker)
        capturer.set_occupancy_detector(occupancy_detector)
        capturer.set_highlight_detector(highlight_detector)
        capturer.set_pixel_scanner(pixel_scanner)
        capturer.set_move_callback(_on_move_detected)
        capturer.start()
    writer.ack(cmd["commandId"])


def handle_set_fps(cmd: dict) -> None:
    if capturer:
        capturer.set_fps(float(cmd.get("fps", 5)))
    writer.ack(cmd["commandId"])


def handle_set_preview(cmd: dict) -> None:
    if capturer:
        capturer.send_previews = bool(cmd.get("enabled", True))
    writer.ack(cmd["commandId"])


def handle_save_snapshot(cmd: dict) -> None:
    if capturer:
        path = capturer.save_snapshot(cmd.get("outputDir"))
        if path:
            writer.send({"type": "snapshot_saved", "path": path})
    writer.ack(cmd["commandId"])


def handle_set_debug(cmd: dict) -> None:
    global _debug_mode
    _debug_mode = bool(cmd.get("enabled", False))
    if capturer:
        capturer.debug = _debug_mode
    writer.ack(cmd["commandId"])
    log.info("Debug mode: %s", _debug_mode)


def handle_shutdown(cmd: dict) -> None:
    log.info("Shutdown requested")
    writer.ack(cmd["commandId"])
    _shutdown_event.set()


def handle_detect_board(cmd: dict) -> None:
    global cached_candidates
    writer.send({
        "type": "state_change",
        "state": "SEARCHING",
        "reason": "Scanning captured screen for chessboard candidates",
    })

    frame = capturer.get_latest_frame() if capturer else None
    if frame is None or frame.size == 0:
        writer.send({
            "type": "error",
            "code": "NO_FRAME",
            "message": "No frame captured yet. Start capture first.",
        })
        writer.ack(cmd["commandId"])
        return

    candidates = board_detector.detect(frame)
    cached_candidates = candidates
    writer.send({
        "type": "board_candidates",
        "candidates": [c.to_dict() for c in candidates],
    })

    if candidates:
        writer.send({
            "type": "state_change",
            "state": "CANDIDATE_FOUND",
            "reason": f"Found {len(candidates)} candidate(s) (best score: {candidates[0].score:.2f})",
        })
    else:
        writer.send({
            "type": "state_change",
            "state": "NO_BOARD",
            "reason": "No chessboard candidate detected on the current screen",
        })
    writer.ack(cmd["commandId"])


def handle_select_candidate(cmd: dict) -> None:
    cid = int(cmd.get("candidateId", 0))
    target = next((c for c in cached_candidates if c.candidate_id == cid), None)
    if target is None:
        writer.send({
            "type": "error",
            "code": "INVALID_CANDIDATE",
            "message": f"Candidate {cid} not found.",
        })
        writer.ack(cmd["commandId"])
        return

    frame = capturer.get_latest_frame() if capturer else None
    rect = (target.x, target.y, target.w, target.h)
    board_info = board_tracker.lock_board(rect, current_frame=frame)

    # Auto-calibrate baseline background colors from empty ranks
    local_team = "WHITE" if board_tracker.orientation == "white_bottom" else "BLACK"
    if frame is not None:
        highlight_detector.calibrate(frame)
        occupancy_detector.calibrate_baseline(frame)
        pixel_scanner.initialize(board_tracker, frame)
        if capturer:
            capturer.set_pixel_scanner(pixel_scanner)
            capturer.set_move_callback(_on_move_detected)
    virtual_board.initialize_standard(local_team)

    writer.send({
        "type": "board_locked",
        "rect": board_info["rect"],
        "orientation": board_info["orientation"],
        "squareWidth": board_info["squareWidth"],
        "squareHeight": board_info["squareHeight"],
        "squares": board_info["squares"],
    })
    writer.send({
        "type": "state_change",
        "state": "BOARD_LOCKED",
        "reason": f"Locked onto candidate {cid} ({target.w}x{target.h})",
    })
    writer.ack(cmd["commandId"])


def handle_set_manual_board(cmd: dict) -> None:
    left = int(cmd.get("left", 0))
    top = int(cmd.get("top", 0))
    width = int(cmd.get("width", 0))
    height = int(cmd.get("height", 0))
    orientation = cmd.get("orientation", "white_bottom")

    if width > 0 and height > 0:
        frame = capturer.get_latest_frame() if capturer else None
        board_info = board_tracker.lock_board((left, top, width, height), current_frame=frame, orientation=orientation)
        local_team = "WHITE" if orientation == "white_bottom" else "BLACK"
        if frame is not None:
            highlight_detector.calibrate(frame)
            occupancy_detector.calibrate_baseline(frame)
            pixel_scanner.initialize(board_tracker, frame)
            if capturer:
                capturer.set_pixel_scanner(pixel_scanner)
                capturer.set_move_callback(_on_move_detected)
        virtual_board.initialize_standard(local_team)

        writer.send({
            "type": "board_locked",
            "rect": board_info["rect"],
            "orientation": board_info["orientation"],
            "squareWidth": board_info["squareWidth"],
            "squareHeight": board_info["squareHeight"],
            "squares": board_info["squares"],
        })
        writer.send({
            "type": "state_change",
            "state": "BOARD_LOCKED",
            "reason": f"Manual board calibrated and locked ({width}x{height})",
        })
        _send_board_debug(final_action=f"Manual board locked ({width}x{height})")
    else:
        board_tracker.unlock_board()
        pixel_scanner.is_initialized = False
        if capturer:
            capturer.set_pixel_scanner(None)
        writer.send({"type": "board_unlocked"})
        writer.send({"type": "state_change", "state": "NO_BOARD", "reason": "Board unlocked"})

    writer.ack(cmd["commandId"])


def handle_lock_board(cmd: dict) -> None:
    if board_tracker.rect:
        board_info = board_tracker.get_board_info()
        writer.send({
            "type": "board_locked",
            "rect": board_info["rect"],
            "orientation": board_info["orientation"],
            "squareWidth": board_info["squareWidth"],
            "squareHeight": board_info["squareHeight"],
            "squares": board_info["squares"],
        })
        writer.send({"type": "state_change", "state": "BOARD_LOCKED", "reason": "Board locked"})
    elif cached_candidates:
        handle_select_candidate({"candidateId": cached_candidates[0].candidate_id, "commandId": cmd["commandId"]})
        return
    else:
        writer.send({"type": "error", "code": "NO_BOARD_SELECTED", "message": "No board detected or calibrated to lock."})
    writer.ack(cmd["commandId"])


def handle_unlock_board(cmd: dict) -> None:
    board_tracker.unlock_board()
    pixel_scanner.is_initialized = False
    if capturer:
        capturer.set_pixel_scanner(None)
    writer.send({"type": "board_unlocked"})
    writer.send({"type": "state_change", "state": "NO_BOARD", "reason": "Board unlocked by user"})
    writer.ack(cmd["commandId"])


def handle_initialize_game(cmd: dict) -> None:
    if not board_tracker.rect:
        writer.send({"type": "error", "code": "NO_BOARD_SELECTED", "message": "Lock the board before scanning it."})
        writer.ack(cmd["commandId"])
        return
    frame = capturer.get_latest_frame() if capturer else None
    if frame is None:
        writer.send({"type": "error", "code": "NO_FRAME", "message": "Start capture before scanning the board."})
        writer.ack(cmd["commandId"])
        return
    highlight_detector.calibrate(frame)
    occupancy_detector.calibrate_baseline(frame)
    local_team = "WHITE" if board_tracker.orientation == "white_bottom" else "BLACK"
    virtual_board.initialize_standard(local_team)
    pixel_scanner.initialize(board_tracker, frame)
    if capturer:
        capturer.set_pixel_scanner(pixel_scanner)
        capturer.set_move_callback(_on_move_detected)
    _send_board_debug(final_action=f"Board scanned. Watching {local_team.lower()} moves.")
    writer.ack(cmd["commandId"])


def handle_find_board(cmd: dict) -> None:
    """[ key workflow: find, lock, calibrate center background, and establish board boundaries/orientation without forcing starting pieces."""
    global capturer
    if capturer is None or not capturer.is_running():
        monitors = ScreenCapturer.list_monitors()
        if monitors:
            board_tracker.set_monitor_offset((monitors[0]["left"], monitors[0]["top"]), monitors[0]["scale"])
        capturer = ScreenCapturer(
            monitor_index=0,
            target_fps=10.0,
            send_previews=True,
            writer=writer,
            debug=_debug_mode,
        )
        capturer.set_tracker(board_tracker)
        capturer.set_occupancy_detector(occupancy_detector)
        capturer.set_highlight_detector(highlight_detector)
        capturer.set_pixel_scanner(pixel_scanner)
        capturer.set_move_callback(_on_move_detected)
        capturer.start()
        time.sleep(0.15)

    frame = capturer.get_latest_frame() if capturer else None
    if frame is None:
        writer.send({"type": "error", "code": "NO_FRAME", "message": "Could not capture screen frame."})
        writer.ack(cmd["commandId"])
        return
    candidates = board_detector.detect(frame)
    if not candidates:
        writer.send({"type": "error", "code": "NO_BOARD", "message": "Could not find a chessboard in the current frame."})
        writer.ack(cmd["commandId"])
        return

    target = candidates[0]
    board_info = board_tracker.lock_board((target.x, target.y, target.w, target.h), current_frame=frame)
    # Calibrate background colors from corners (white, light pink, and any highlight)
    highlight_detector.calibrate(frame)
    occupancy_detector.calibrate_baseline(frame)

    # Divide board into 2 halves to determine orientation from piece presence
    top_squares = [sq for sq in board_tracker.squares.values() if sq.row <= 3]
    bottom_squares = [sq for sq in board_tracker.squares.values() if sq.row >= 4]

    observations = occupancy_detector.process_frame(frame)

    def evaluate_square_score(sq):
        w_ink, b_ink = occupancy_detector.get_extreme_ink_counts(frame, sq)
        obs = observations.get(sq.name)
        diff = obs.diff_score if obs else 0.0
        score = max(w_ink, b_ink) * 100.0 + diff
        return score, w_ink, b_ink

    top_ranked = [(sq, *evaluate_square_score(sq)) for sq in top_squares]
    top_ranked.sort(key=lambda item: item[1], reverse=True)
    top_16 = top_ranked[:16]

    bottom_ranked = [(sq, *evaluate_square_score(sq)) for sq in bottom_squares]
    bottom_ranked.sort(key=lambda item: item[1], reverse=True)
    bottom_16 = bottom_ranked[:16]

    top_white = sum(item[2] for item in top_16)
    top_black = sum(item[3] for item in top_16)
    bottom_white = sum(item[2] for item in bottom_16)
    bottom_black = sum(item[3] for item in bottom_16)

    if (bottom_white - bottom_black) >= (top_white - top_black):
        bottom_team = "WHITE"
    else:
        bottom_team = "BLACK"

    board_tracker.set_orientation("white_bottom" if bottom_team == "WHITE" else "black_bottom")
    board_info = board_tracker.get_board_info()
    highlight_detector.calibrate(frame)

    # Initialize empty virtual board without forcing pieces (scan or R key will populate)
    virtual_board.reset()
    virtual_board.local_team = bottom_team

    # Initialize ultra-fast pixel scanner with 64 squares and stored baselines
    pixel_scanner.initialize(board_tracker, frame)
    if capturer:
        capturer.set_pixel_scanner(pixel_scanner)
        capturer.set_move_callback(_on_move_detected)

    writer.send({
        "type": "board_locked",
        "rect": board_info["rect"],
        "orientation": board_info["orientation"],
        "squareWidth": board_info["squareWidth"],
        "squareHeight": board_info["squareHeight"],
        "squares": board_info["squares"],
    })
    writer.send({
        "type": "state_change",
        "state": "BOARD_LOCKED",
        "reason": f"[ found and locked board (orientation: {board_info['orientation']})",
    })
    _send_board_debug(
        final_action=f"Board locked ({board_info['orientation']}). Movement scanner active. Press R to reset pieces.",
        standard_piece_setup=False,
    )
    writer.ack(cmd["commandId"])


def handle_reset_pieces(cmd: dict) -> None:
    """R key workflow: reset pieces position to the standard 16 vs 16 starting position on the currently locked board."""
    if not board_tracker.rect:
        writer.send({
            "type": "error",
            "code": "NO_BOARD_LOCKED",
            "message": "No board is currently locked. Press [ to find and lock board first.",
        })
        writer.ack(cmd["commandId"])
        return

    frame = capturer.get_latest_frame() if capturer else None
    if frame is not None:
        highlight_detector.calibrate(frame)
        occupancy_detector.calibrate_baseline(frame)

    local_team = "WHITE" if board_tracker.orientation == "white_bottom" else "BLACK"
    assigned_teams = {}
    for file_name in "abcdefgh":
        assigned_teams[f"{file_name}1"] = "WHITE"
        assigned_teams[f"{file_name}2"] = "WHITE"
        assigned_teams[f"{file_name}7"] = "BLACK"
        assigned_teams[f"{file_name}8"] = "BLACK"

    virtual_board.initialize_from_assigned_teams(assigned_teams, local_team)

    if frame is not None:
        pixel_scanner.initialize(board_tracker, frame)
        if capturer:
            capturer.set_pixel_scanner(pixel_scanner)
            capturer.set_move_callback(_on_move_detected)

    writer.send({
        "type": "state_change",
        "state": "BOARD_LOCKED",
        "reason": f"R reset piece positions to standard 16 vs 16 opening (playing {local_team.lower()})",
    })
    _send_board_debug(
        final_action=f"Piece positions reset to standard 16 vs 16. Playing {local_team.lower()}.",
        standard_piece_setup=True,
    )
    writer.ack(cmd["commandId"])


def handle_reset_game(cmd: dict) -> None:
    """Legacy/combo workflow: find, lock, calibrate center background, and establish 16+16 pieces by dividing the board into 2 sides."""
    global capturer
    if capturer is None or not capturer.is_running():
        monitors = ScreenCapturer.list_monitors()
        if monitors:
            board_tracker.set_monitor_offset((monitors[0]["left"], monitors[0]["top"]), monitors[0]["scale"])
        capturer = ScreenCapturer(
            monitor_index=0,
            target_fps=10.0,
            send_previews=True,
            writer=writer,
            debug=_debug_mode,
        )
        capturer.set_tracker(board_tracker)
        capturer.set_occupancy_detector(occupancy_detector)
        capturer.set_highlight_detector(highlight_detector)
        capturer.set_pixel_scanner(pixel_scanner)
        capturer.set_move_callback(_on_move_detected)
        capturer.start()
        time.sleep(0.15)

    frame = capturer.get_latest_frame() if capturer else None
    if frame is None:
        writer.send({"type": "error", "code": "NO_FRAME", "message": "Could not capture screen frame."})
        writer.ack(cmd["commandId"])
        return
    candidates = board_detector.detect(frame)
    if not candidates:
        writer.send({"type": "error", "code": "NO_BOARD", "message": "Could not find a chessboard in the current frame."})
        writer.ack(cmd["commandId"])
        return

    target = candidates[0]
    board_info = board_tracker.lock_board((target.x, target.y, target.w, target.h), current_frame=frame)
    # Calibrate background colors from corners (white, light pink, and any highlight)
    highlight_detector.calibrate(frame)
    occupancy_detector.calibrate_baseline(frame)

    # Divide board into 2 halves: top half (rows 0-3) and bottom half (rows 4-7)
    # Each half has 32 squares, and should contain the 16 pieces of that team
    top_squares = [sq for sq in board_tracker.squares.values() if sq.row <= 3]
    bottom_squares = [sq for sq in board_tracker.squares.values() if sq.row >= 4]

    observations = occupancy_detector.process_frame(frame)

    def evaluate_square_score(sq):
        w_ink, b_ink = occupancy_detector.get_extreme_ink_counts(frame, sq)
        obs = observations.get(sq.name)
        diff = obs.diff_score if obs else 0.0
        # Priority score for occupied piece presence
        score = max(w_ink, b_ink) * 100.0 + diff
        return score, w_ink, b_ink

    top_ranked = [(sq, *evaluate_square_score(sq)) for sq in top_squares]
    top_ranked.sort(key=lambda item: item[1], reverse=True)
    top_16 = top_ranked[:16]

    bottom_ranked = [(sq, *evaluate_square_score(sq)) for sq in bottom_squares]
    bottom_ranked.sort(key=lambda item: item[1], reverse=True)
    bottom_16 = bottom_ranked[:16]

    # Pool ink counts across the 16 squares on each side for rock-solid team color recognition
    top_white = sum(item[2] for item in top_16)
    top_black = sum(item[3] for item in top_16)
    bottom_white = sum(item[2] for item in bottom_16)
    bottom_black = sum(item[3] for item in bottom_16)

    if (bottom_white - bottom_black) >= (top_white - top_black):
        bottom_team = "WHITE"
        top_team = "BLACK"
    else:
        bottom_team = "BLACK"
        top_team = "WHITE"

    board_tracker.set_orientation("white_bottom" if bottom_team == "WHITE" else "black_bottom")
    board_info = board_tracker.get_board_info()
    # Recalibrate after finalizing orientation so any highlights already on
    # screen are stored under the same algebraic square names as the scanner.
    highlight_detector.calibrate(frame)
    observations = occupancy_detector.process_frame(frame)

    # R is an opening-position setup. Once the board orientation has been
    # finalized, use algebraic ranks rather than the pre-flip screen-square
    # objects above. This is correct for either side at the bottom: white owns
    # ranks 1/2 and black owns ranks 7/8 regardless of screen rotation.
    assigned_teams = {}
    for file_name in "abcdefgh":
        assigned_teams[f"{file_name}1"] = "WHITE"
        assigned_teams[f"{file_name}2"] = "WHITE"
        assigned_teams[f"{file_name}7"] = "BLACK"
        assigned_teams[f"{file_name}8"] = "BLACK"

    virtual_board.initialize_from_assigned_teams(assigned_teams, bottom_team)
    # Initialize ultra-fast pixel scanner with 64 squares and stored baselines
    pixel_scanner.initialize(board_tracker, frame)
    if capturer:
        capturer.set_pixel_scanner(pixel_scanner)
        capturer.set_move_callback(_on_move_detected)

    writer.send({"type": "board_locked", "rect": board_info["rect"], "orientation": board_info["orientation"], "squareWidth": board_info["squareWidth"], "squareHeight": board_info["squareHeight"], "squares": board_info["squares"]})
    writer.send({"type": "state_change", "state": "BOARD_LOCKED", "reason": f"R reset locked board with 16 {top_team.lower()} vs 16 {bottom_team.lower()} pieces"})
    _send_board_debug(
        final_action=f"Board locked with 16 vs 16 pieces. You are playing {bottom_team.lower()}.",
        standard_piece_setup=True,
    )
    writer.ack(cmd["commandId"])


def handle_set_orientation(cmd: dict) -> None:
    orientation = cmd.get("orientation", "white_bottom")
    board_tracker.set_orientation(orientation)
    if board_tracker.rect:
        frame = capturer.get_latest_frame() if capturer else None
        if frame is not None:
            highlight_detector.calibrate(frame)
            pixel_scanner.initialize(board_tracker, frame)
        board_info = board_tracker.get_board_info()
        writer.send({
            "type": "board_locked",
            "rect": board_info["rect"],
            "orientation": board_info["orientation"],
            "squareWidth": board_info["squareWidth"],
            "squareHeight": board_info["squareHeight"],
            "squares": board_info["squares"],
        })
    writer.ack(cmd["commandId"])


def handle_calibrate_occupancy(cmd: dict) -> None:
    frame = capturer.get_latest_frame() if capturer else None
    if frame is not None:
        ok = occupancy_detector.calibrate_baseline(frame)
        if ok:
            log.info("Occupancy baseline recalibrated")
        else:
            log.warning("Could not calibrate baseline: no board locked")
    writer.ack(cmd["commandId"])


def handle_get_occupancy(cmd: dict) -> None:
    frame = capturer.get_latest_frame() if capturer else None
    if frame is not None and board_tracker.squares:
        obs = occupancy_detector.process_frame(frame)
        summary = occupancy_detector.get_summary()
        from datetime import datetime, timezone
        writer.send({
            "type": "square_occupancy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
            "squares": {k: v.to_dict() for k, v in obs.items()},
        })
    writer.ack(cmd["commandId"])


def handle_set_pixel_palette(cmd: dict) -> None:
    colors = cmd.get("colors")
    if not isinstance(colors, dict):
        raise ValueError("Square palette colors must be an object.")
    pixel_scanner.set_palette(colors)
    writer.ack(cmd["commandId"])


def handle_sample_screen_color(cmd: dict) -> None:
    command_id = cmd["commandId"]
    try:
        monitor_index = cmd.get("monitorIndex")
        x_ratio = cmd.get("xRatio")
        y_ratio = cmd.get("yRatio")
        if not isinstance(monitor_index, int) or isinstance(monitor_index, bool):
            raise ValueError("Monitor index must be an integer.")
        if not isinstance(x_ratio, (int, float)) or not 0 <= x_ratio < 1:
            raise ValueError("Screen x coordinate is outside the monitor.")
        if not isinstance(y_ratio, (int, float)) or not 0 <= y_ratio < 1:
            raise ValueError("Screen y coordinate is outside the monitor.")

        monitors = ScreenCapturer.list_monitors()
        if monitor_index < 0 or monitor_index >= len(monitors):
            raise ValueError(f"Monitor {monitor_index} is not available.")
        monitor = monitors[monitor_index]
        x = monitor["left"] + min(monitor["width"] - 1, int(x_ratio * monitor["width"]))
        y = monitor["top"] + min(monitor["height"] - 1, int(y_ratio * monitor["height"]))

        # Ask MSS for only the selected pixel instead of capturing a full display.
        import mss
        with mss.MSS() as sct:
            pixel = sct.grab({"left": x, "top": y, "width": 1, "height": 1})
        blue, green, red = pixel.raw[:3]
        writer.send({
            "type": "screen_color_sampled",
            "commandId": command_id,
            "color": f"#{red:02X}{green:02X}{blue:02X}",
        })
    except Exception as exc:
        log.exception("Could not sample desktop color")
        writer.send({
            "type": "screen_color_sampled",
            "commandId": command_id,
            "error": str(exc),
        })


HANDLERS = {
    "get_monitors":        handle_get_monitors,
    "start_capture":       handle_start_capture,
    "stop_capture":        handle_stop_capture,
    "set_monitor":         handle_set_monitor,
    "set_fps":             handle_set_fps,
    "set_preview_enabled": handle_set_preview,
    "save_snapshot":       handle_save_snapshot,
    "set_debug_mode":      handle_set_debug,
    "set_locked_board":    handle_set_manual_board,
    "set_manual_board":    handle_set_manual_board,
    "detect_board":        handle_detect_board,
    "select_candidate":    handle_select_candidate,
    "lock_board":          handle_lock_board,
    "unlock_board":        handle_unlock_board,
    "set_orientation":     handle_set_orientation,
    "calibrate_occupancy": handle_calibrate_occupancy,
    "get_occupancy":       handle_get_occupancy,
    "set_pixel_palette":   handle_set_pixel_palette,
    "sample_screen_color": handle_sample_screen_color,
    "find_board":          handle_find_board,
    "reset_pieces":        handle_reset_pieces,
    "initialize_game":     handle_initialize_game,
    "reset_game":          handle_reset_game,
    "shutdown":            handle_shutdown,
}


def dispatch(cmd: dict) -> None:
    msg_type = cmd.get("type", "")
    handler = HANDLERS.get(msg_type)
    if handler:
        try:
            handler(cmd)
        except Exception as exc:
            log.exception("Error handling command %s", msg_type)
            writer.send({
                "type": "error",
                "code": "COMMAND_ERROR",
                "commandId": cmd.get("commandId"),
                "message": f"Error in {msg_type}: {exc}",
                "detail": str(exc),
            })
    else:
        log.warning("Unknown command type: %s", msg_type)
        writer.send({
            "type": "error",
            "code": "UNKNOWN_COMMAND",
            "message": f"Unknown command: {msg_type}",
        })


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    log.info("Chess Vision FX backend v%s starting (Python %s)", VERSION, sys.version.split()[0])

    # Announce readiness
    import platform
    writer.send({
        "type": "ready",
        "version": VERSION,
        "pythonVersion": platform.python_version(),
    })

    # Emit initial monitor list
    monitors = ScreenCapturer.list_monitors()
    writer.send({"type": "monitor_list", "monitors": monitors})

    # Send initial state
    writer.send({
        "type": "state_change",
        "state": "NO_BOARD",
        "reason": "Backend started – no board selected yet",
    })

    # Read commands from Electron on stdin
    for cmd in read_commands(sys.stdin):
        dispatch(cmd)
        if _shutdown_event.is_set():
            break

    # Cleanup
    if capturer and capturer.is_running():
        capturer.stop()
    log.info("Backend exiting cleanly")


if __name__ == "__main__":
    main()
