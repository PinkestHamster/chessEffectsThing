"""
pixel_scanner.py – Ultra-Fast Chessboard Pixel Recognition.

Scans precomputed fixed pixel coordinates near the top-left area of every square.
Uses the selected board-theme palette. The constants below are the built-in
Chess.com Pink defaults; the control UI replaces them through set_palette():
  - Highlighted light square: #EEAEB6 (RGB: 238, 174, 182)
  - Highlighted dark square:  #EC9BA8 (RGB: 236, 155, 168)
  - Light square:             #FEFFFE (RGB: 254, 255, 254)
  - Dark square:              #FBD9E1 (RGB: 251, 217, 225)
  - Checked king, light/dark: #F19299 / #EF818C
  - Capturable target, light/dark: #DADBDA / #CC959C

Verifies true real movement by ensuring exactly two move-highlight squares are
present and that the highlight pair has changed. Selection states that expose a
capturable-target color are rejected separately.
This prevents piece-selection colors from being mistaken for a movement.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Set, Tuple
import numpy as np

log = logging.getLogger(__name__)

# ─── Built-in Board Colors (RGB & BGR) ─────────────────────────────────────────
# Highlighted light square: #EEAEB6 (RGB: 238, 174, 182)
HL_LIGHT_RGB = np.array([238.0, 174.0, 182.0], dtype=np.float32)
HL_LIGHT_BGR = np.array([182.0, 174.0, 238.0], dtype=np.float32)

# Highlighted dark square:  #EC9BA8 (RGB: 236, 155, 168)
HL_DARK_RGB = np.array([236.0, 155.0, 168.0], dtype=np.float32)
HL_DARK_BGR = np.array([168.0, 155.0, 236.0], dtype=np.float32)

# Light square (normal background): #FEFFFE (RGB: 254, 255, 254)
LIGHT_SQ_RGB = np.array([254.0, 255.0, 254.0], dtype=np.float32)
LIGHT_SQ_BGR = np.array([254.0, 255.0, 254.0], dtype=np.float32)

# Dark square (normal background):  #FBD9E1 (RGB: 251, 217, 225)
DARK_SQ_RGB = np.array([251.0, 217.0, 225.0], dtype=np.float32)
DARK_SQ_BGR = np.array([225.0, 217.0, 251.0], dtype=np.float32)

# Checked king on light square: #F19299 (RGB: 241, 146, 153)
CHECK_LIGHT_RGB = np.array([241.0, 146.0, 153.0], dtype=np.float32)
CHECK_LIGHT_BGR = np.array([153.0, 146.0, 241.0], dtype=np.float32)

# Checked king on dark square: #EF818C (RGB: 239, 129, 140)
CHECK_DARK_RGB = np.array([239.0, 129.0, 140.0], dtype=np.float32)
CHECK_DARK_BGR = np.array([140.0, 129.0, 239.0], dtype=np.float32)

# When a piece is selected, capturable target on light square: #DADBDA (RGB: 218, 219, 218)
TARGET_LIGHT_RGB = np.array([218.0, 219.0, 218.0], dtype=np.float32)
TARGET_LIGHT_BGR = np.array([218.0, 219.0, 218.0], dtype=np.float32)

# When a piece is selected, capturable target on dark square: #CC959C (RGB: 204, 149, 156)
TARGET_DARK_RGB = np.array([204.0, 149.0, 156.0], dtype=np.float32)
TARGET_DARK_BGR = np.array([156.0, 149.0, 204.0], dtype=np.float32)

# Defaults supplied until the selected UI theme is applied.
SQUARE_COLORS_RGB = {
    "move_highlight_light": HL_LIGHT_RGB,
    "move_highlight_dark": HL_DARK_RGB,
    "normal_light": LIGHT_SQ_RGB,
    "normal_dark": DARK_SQ_RGB,
    "checked_king_light": CHECK_LIGHT_RGB,
    "checked_king_dark": CHECK_DARK_RGB,
    "capturable_target_light": TARGET_LIGHT_RGB,
    "capturable_target_dark": TARGET_DARK_RGB,
    "capturable_target_highlight_light": None,
    "capturable_target_highlight_dark": None,
}


def is_valid_chess_geometry(sq1: str, sq2: str) -> bool:
    """
    Check if two squares form a valid geometric chess move (orthogonal, diagonal, or knight leap).
    Rejects impossible non-chess pairings (e.g. e4 -> f7 where df=1, dr=3).
    """
    if sq1 == sq2 or len(sq1) != 2 or len(sq2) != 2:
        return False
    f1, r1 = ord(sq1[0]) - ord("a"), int(sq1[1])
    f2, r2 = ord(sq2[0]) - ord("a"), int(sq2[1])
    df = abs(f2 - f1)
    dr = abs(r2 - r1)
    # 1. Straight line (rank or file)
    if (df == 0 and dr > 0) or (dr == 0 and df > 0):
        return True
    # 2. Diagonal line
    if df == dr and df > 0:
        return True
    # 3. Knight leap
    if (df == 1 and dr == 2) or (df == 2 and dr == 1):
        return True
    return False


class PixelScanner:
    """
    Ultra-fast 64-square top-right corner pixel recognition with real-movement verification.
    """

    def __init__(self, board_tracker=None) -> None:
        self.board_tracker = board_tracker
        self.is_initialized: bool = False
        self.square_colors_rgb: Dict[str, Optional[np.ndarray]] = {
            name: color.copy() if color is not None else None
            for name, color in SQUARE_COLORS_RGB.items()
        }

        # Precomputed sample coordinates: list of (sq_name, y1, y2, x1, x2, is_light)
        self._sample_targets: List[Tuple[str, int, int, int, int, bool]] = []
        self._sample_regions: Dict[str, Tuple[int, int, int, int]] = {}
        self._square_names: List[str] = []

        # Baseline sampled RGB values per square: dict of sq_name -> np.ndarray([r, g, b])
        self.baseline_rgb: Dict[str, np.ndarray] = {}

        # Set of squares currently recognized from the last verified real movement
        self._old_highlighted: Set[str] = set()
        self._prev_highlighted: Set[str] = set()
        self._old_dest: Optional[str] = None
        self._initial_highlighted: Set[str] = set()
        self.last_scan_highlights: List[str] = []
        self.last_scan_raw_highlights: List[str] = []
        self.last_scan_targets: List[str] = []
        self.last_square_status: Dict[str, str] = {}
        self.last_highlight_candidates: List[dict] = []
        self.last_rejected_pair: Optional[List[str]] = None
        self._square_status_history: Dict[str, List[str]] = {}
        self._stable_square_status: Dict[str, str] = {}

    def set_palette(self, colors: Dict[str, Optional[List[int]]]) -> None:
        """Replace the active square palette with validated RGB values."""
        if set(colors) != set(SQUARE_COLORS_RGB):
            raise ValueError("Palette must define all ten square color names.")

        optional_names = {
            "capturable_target_highlight_light",
            "capturable_target_highlight_dark",
        }
        normalized: Dict[str, Optional[np.ndarray]] = {}
        for name, value in colors.items():
            if value is None and name in optional_names:
                normalized[name] = None
                continue
            if value is None:
                raise ValueError(f"Color for {name} cannot be empty.")
            color = np.asarray(value, dtype=np.float32)
            if color.shape != (3,) or not np.all(np.isfinite(color)) or np.any(color < 0) or np.any(color > 255):
                raise ValueError(f"Invalid RGB value for {name}.")
            normalized[name] = color
        self.square_colors_rgb = normalized
        log.info("Pixel scanner palette updated.")

    def set_last_move(self, source: str, destination: str) -> None:
        """Record the verified source and destination squares of the previous move."""
        self._old_dest = destination
        self._old_highlighted = {source, destination}
        self._prev_highlighted = {source, destination}

    def rollback_last_scan(self) -> None:
        """Rollback _old_highlighted if the move was rejected by the virtual board."""
        self._old_highlighted = set(self._prev_highlighted)

    def classify_square(self, patch_rgb: np.ndarray, is_light: bool) -> str:
        """
        Classifies square color against the active palette into HIGHLIGHT,
        NORMAL, CHECK, TARGET, or OTHER.
        """
        target_hl = self.square_colors_rgb["move_highlight_light" if is_light else "move_highlight_dark"]
        target_normal = self.square_colors_rgb["normal_light" if is_light else "normal_dark"]
        target_check = self.square_colors_rgb["checked_king_light" if is_light else "checked_king_dark"]

        d_hl = float(np.linalg.norm(patch_rgb - target_hl))
        d_normal = float(np.linalg.norm(patch_rgb - target_normal))
        d_check = float(np.linalg.norm(patch_rgb - target_check))
        target_colors = self._capturable_target_colors(is_light)
        d_target = min(float(np.linalg.norm(patch_rgb - color)) for color in target_colors)

        # Compare both target shades so a selection is still recognized if the
        # sampled square parity is off, without letting a nearby shade override
        # an exact match for another known color.
        min_d = min(d_hl, d_normal, d_check, d_target)
        if min_d > 35.0:
            return "OTHER"
        if min_d == d_hl:
            return "HIGHLIGHT"
        if min_d == d_normal:
            return "NORMAL"
        if min_d == d_check:
            return "CHECK"
        return "TARGET"

    def _capturable_target_colors(self, is_light: bool) -> List[np.ndarray]:
        suffix = "light" if is_light else "dark"
        colors = [
            self.square_colors_rgb[f"capturable_target_{suffix}"],
            self.square_colors_rgb[f"capturable_target_highlight_{suffix}"],
        ]
        return [color for color in colors if color is not None]

    def _is_capturable_target_sample(self, patch_rgb: np.ndarray, is_light: bool) -> bool:
        targets = self._capturable_target_colors(is_light)
        target_distance = min(float(np.linalg.norm(patch_rgb - color)) for color in targets)
        other_colors = [
            self.square_colors_rgb[f"move_highlight_{'light' if is_light else 'dark'}"],
            self.square_colors_rgb[f"normal_{'light' if is_light else 'dark'}"],
            self.square_colors_rgb[f"checked_king_{'light' if is_light else 'dark'}"],
        ]
        other_distance = min(float(np.linalg.norm(patch_rgb - color)) for color in other_colors)
        return target_distance <= 24.0 and target_distance < other_distance

    def is_square_highlighted(self, name: str, patch_rgb: np.ndarray, is_light: bool) -> bool:
        """Check if square RGB matches its move highlight target color and is closest to it."""
        return self.classify_square(patch_rgb, is_light) == "HIGHLIGHT"

    def is_square_normal(self, name: str, patch_rgb: np.ndarray, is_light: bool) -> bool:
        """Check if square RGB matches normal background."""
        return self.classify_square(patch_rgb, is_light) == "NORMAL"

    def is_square_checked_king(self, patch_rgb: np.ndarray, is_light: bool) -> bool:
        """Check if square RGB matches checked king color."""
        return self.classify_square(patch_rgb, is_light) == "CHECK"

    def is_square_capturable_target(self, patch_rgb: np.ndarray, is_light: bool) -> bool:
        """Check if square RGB matches capturable target color during piece selection."""
        return self.classify_square(patch_rgb, is_light) == "TARGET"

    def initialize(self, board_tracker, frame: np.ndarray) -> bool:
        """
        Precompute one inset top-right corner sample per square and calibrate
        its RGB baseline.
        """
        self.board_tracker = board_tracker
        if frame is None or frame.size == 0 or not board_tracker or not board_tracker.rect:
            return False

        fh, fw = frame.shape[:2]
        self._sample_targets.clear()
        self._sample_regions.clear()
        self._square_names.clear()
        self.baseline_rgb.clear()
        self._old_source = None
        self._old_dest = None
        self.last_scan_highlights = []
        self.last_scan_raw_highlights = []
        self.last_scan_targets = []
        self.last_square_status = {}
        self.last_highlight_candidates = []
        self.last_rejected_pair = None
        self._square_status_history.clear()
        self._stable_square_status.clear()

        # Iterate over all 64 squares from board_tracker
        for name, sq in board_tracker.squares.items():
            x, y, w, h = sq.bounds
            sample_width = min(max(3, int(round(w * 0.05))), max(1, w // 3))
            sample_height = min(max(3, int(round(h * 0.05))), max(1, h // 3))
            off_x = max(2, int(w * 0.04))
            off_y = max(2, int(h * 0.04))
            x1 = max(0, min(fw - sample_width, x + w - off_x - sample_width))
            y1 = max(0, min(fh - sample_height, y + off_y))
            sample_region = (y1, y1 + sample_height, x1, x1 + sample_width)
            self._sample_regions[name] = sample_region
            y1, y2, x1, x2 = sample_region

            is_light = (sq.col + sq.row) % 2 == 0
            self._sample_targets.append((name, y1, y2, x1, x2, is_light))
            self._square_names.append(name)

        # Record baseline RGB values from initial frame
        for name, y1, y2, x1, x2, is_light in self._sample_targets:
            patch = frame[y1:y2, x1:x2]
            if patch.size > 0:
                rgb_mean = np.median(patch, axis=(0, 1))[::-1].astype(np.float32)
            else:
                rgb_mean = self.square_colors_rgb["normal_light" if is_light else "normal_dark"].copy()

            self.baseline_rgb[name] = rgb_mean

        # Remember startup samples classified as highlights so static color
        # artifacts from pieces can be ignored until the sampled color changes.
        init_hl: Set[str] = set()
        for name, y1, y2, x1, x2, is_light in self._sample_targets:
            patch = frame[y1:y2, x1:x2]
            if patch.size and self.is_square_highlighted(
                name,
                np.median(patch, axis=(0, 1))[::-1],
                is_light,
            ):
                init_hl.add(name)

        self._old_highlighted = init_hl
        self._prev_highlighted = set(init_hl)
        self._initial_highlighted = set(init_hl)
        self.is_initialized = True
        log.info(
            "PixelScanner initialized for 64 squares (%d startup color candidates; using frame as baseline)",
            len(init_hl),
        )
        return True

    def scan_frame(self, frame: np.ndarray) -> Optional[List[str]]:
        """
        Continuously scan sample points as fast as possible.
        Verifies a true real movement:
          1. Exactly 2 squares are currently highlighted.
          2. The set of highlighted squares differs from the old 2 highlighted squares.
          3. If the new move is not capturing on the old destination, the old destination
             must also be confirmed unhighlighted.
        Returns list of 2 changed squares [sq_source, sq_dest] when verified, or None.
        """
        if not self.is_initialized or frame is None or frame.size == 0:
            return None

        current_hl_list: List[str] = []
        current_target_list: List[str] = []
        square_status: Dict[str, str] = {}
        highlight_candidates = []
        has_capturable_target: bool = False
        square_rgb_map: Dict[str, np.ndarray] = {}

        # 64-square sample loop
        for name, y1, y2, x1, x2, is_light in self._sample_targets:
            patch = frame[y1:y2, x1:x2]
            if not patch.size:
                continue

            rgb = np.median(patch, axis=(0, 1))[::-1]
            square_rgb_map[name] = rgb
            is_target = self._is_capturable_target_sample(rgb, is_light)
            sq_type = "TARGET" if is_target else self.classify_square(rgb, is_light)

            highlight_candidates.append({
                "square": name,
                "rgb": [int(round(channel)) for channel in rgb],
                "lightDistance": round(float(np.linalg.norm(rgb - self.square_colors_rgb["move_highlight_light"])), 1),
                "darkDistance": round(float(np.linalg.norm(rgb - self.square_colors_rgb["move_highlight_dark"])), 1),
                "squareLight": is_light,
            })
            square_status[name] = {
                "NORMAL": "L" if is_light else "D",
                "HIGHLIGHT": "HL" if is_light else "HD",
                "CHECK": "CL" if is_light else "CD",
                "TARGET": "T",
            }.get(sq_type, "?")
            if is_target:
                has_capturable_target = True
                current_target_list.append(name)
                square_status[name] = "T"
            elif sq_type == "HIGHLIGHT":
                current_hl_list.append(name)

        self.last_scan_raw_highlights = current_hl_list.copy()
        self.last_scan_targets = current_target_list
        for name, status in square_status.items():
            history = self._square_status_history.setdefault(name, [])
            history.append(status)
            if len(history) > 5:
                history.pop(0)
            if len(history) < 3:
                self._stable_square_status[name] = status
                continue
            counts = {item: history.count(item) for item in set(history)}
            most_common = max(counts, key=counts.get)
            if counts[most_common] >= 3:
                self._stable_square_status[name] = most_common
        self.last_square_status = dict(self._stable_square_status)
        self.last_highlight_candidates = sorted(
            highlight_candidates,
            key=lambda candidate: min(candidate["lightDistance"], candidate["darkDistance"]),
        )[:5]
        current_hl_set = set(current_hl_list)
        for name in tuple(self._initial_highlighted):
            if name not in current_hl_set:
                self._initial_highlighted.discard(name)
                continue
            baseline = self.baseline_rgb.get(name)
            current = square_rgb_map.get(name)
            if baseline is not None and current is not None and float(np.linalg.norm(current - baseline)) > 8.0:
                self._initial_highlighted.discard(name)
        current_hl_set.difference_update(self._initial_highlighted)
        self.last_scan_highlights = sorted(current_hl_set)
        # A configured capturable-target indicator means a piece is selected.
        if has_capturable_target:
            return None

        # 1. Exactly 2 squares must be highlighted
        if len(current_hl_set) != 2:
            return None

        # 2. Must not be the same as the previous move's highlights
        if current_hl_set == self._old_highlighted:
            return None

        # A later move may legally *land on* the previous move's source square.
        # Do not reject that square just because it is highlighted again. A
        # capture-target marker already suppresses selection states above.

        # 3. If the new move is not capturing on old_dest, old_dest must also be confirmed unhighlighted
        if self._old_dest and (self._old_dest not in current_hl_set):
            old_dst_rgb = square_rgb_map.get(self._old_dest)
            if old_dst_rgb is not None:
                target_info = next((t for t in self._sample_targets if t[0] == self._old_dest), None)
                if target_info:
                    _, _, _, _, _, is_l = target_info
                    if self.is_square_highlighted(self._old_dest, old_dst_rgb, is_l):
                        return None

        # 5. Geometric sanity check: two squares must form a valid chess geometry
        # (rejects impossible leaps like e4 -> f7 where df=1, dr=3)
        current_move_squares = sorted(current_hl_set)
        if not is_valid_chess_geometry(current_move_squares[0], current_move_squares[1]):
            return None

        # True real movement verified!
        self._prev_highlighted = set(self._old_highlighted)
        self._old_highlighted = current_hl_set
        return current_move_squares
