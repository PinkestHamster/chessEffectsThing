"""
HighlightDetector – fast 5x5 corner background sampling and highlight detection.

Instead of scanning entire square piece blobs, samples the top-left 5x5 corner
zone of each square. Since no chess piece occupies the top-left corner, it
always reflects the square's background color:
  1. light_bg_bgr: white for light squares (~[254, 255, 254])
  2. dark_bg_bgr: light pink for dark squares (~[225, 217, 251])
  3. highlight_bg_bgr: slightly more dark pink for moved piece & source square

When a move happens, exactly 2 squares have their corner color deviate to the
highlight background.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple
import numpy as np

log = logging.getLogger(__name__)

# Exact chess.com board colors provided by theme:
# Light square:   Near-white  #FEFFFE (RGB: 254, 255, 254) -> BGR: [254, 255, 254]
DEFAULT_LIGHT_BG_BGR = np.array([254.0, 255.0, 254.0], dtype=np.float32)

# Dark square:    Pale pink   #FBD9E1 (RGB: 251, 217, 225) -> BGR: [225, 217, 251]
DEFAULT_DARK_BG_BGR = np.array([225.0, 217.0, 251.0], dtype=np.float32)

# Highlight:      Rose pink   #EC9BA8 (RGB: 236, 155, 168) -> BGR: [168, 155, 236]
DEFAULT_HIGHLIGHT_BG_BGR = np.array([168.0, 155.0, 236.0], dtype=np.float32)


class HighlightDetector:
    """Samples top-left 5x5 corners of squares to detect chess.com move highlights."""

    def __init__(self, board_tracker, threshold: float = 20.0) -> None:
        self.board_tracker = board_tracker
        self.threshold = threshold
        self.light_bg_bgr: np.ndarray = DEFAULT_LIGHT_BG_BGR.copy()
        self.dark_bg_bgr: np.ndarray = DEFAULT_DARK_BG_BGR.copy()
        self.highlight_bg_bgr: np.ndarray = DEFAULT_HIGHLIGHT_BG_BGR.copy()
        self.is_calibrated: bool = False
        self._last_highlighted: List[str] = []

    def calibrate(self, frame: np.ndarray) -> bool:
        """
        Calibrate light and dark square background colors from top-left corners of all 64 squares.
        Also detects if squares are already highlighted at calibration time.
        """
        if frame is None or frame.size == 0 or not self.board_tracker.squares:
            return False

        light_samples: List[np.ndarray] = []
        dark_samples: List[np.ndarray] = []
        corner_colors: Dict[str, Tuple[bool, np.ndarray]] = {}

        for name, sq in self.board_tracker.squares.items():
            color = self.get_corner_color(frame, sq)
            if color is None:
                continue
            is_light = (sq.col + sq.row) % 2 == 0
            corner_colors[name] = (is_light, color)
            if is_light:
                light_samples.append(color)
            else:
                dark_samples.append(color)

        if not light_samples or not dark_samples:
            return False

        self.light_bg_bgr = np.median(light_samples, axis=0).astype(np.float32)
        self.dark_bg_bgr = np.median(dark_samples, axis=0).astype(np.float32)
        self.is_calibrated = True

        # Check for any squares already highlighted at calibration time
        highlighted_at_reset: List[str] = []
        highlight_samples: List[np.ndarray] = []
        for name, (is_light, color) in corner_colors.items():
            expected = self.light_bg_bgr if is_light else self.dark_bg_bgr
            dist = float(np.linalg.norm(color - expected))
            if dist > self.threshold:
                highlighted_at_reset.append(name)
                highlight_samples.append(color)

        if len(highlighted_at_reset) == 2 and highlight_samples:
            self.highlight_bg_bgr = np.median(highlight_samples, axis=0).astype(np.float32)
            self._last_highlighted = highlighted_at_reset
            log.info("Found two possible existing move highlights on %s (BGR=%s)",
                     highlighted_at_reset, np.round(self.highlight_bg_bgr, 1))
        else:
            self._last_highlighted = []
            log.info(
                "Calibrated board baseline; ignoring %d ambiguous corner-color deviations",
                len(highlighted_at_reset),
            )

        return True

    def get_corner_color(self, frame: np.ndarray, square) -> Optional[np.ndarray]:
        """
        Sample the top-left 5x5 pixel zone of a square.
        Offset by ~8% (at least 4px) to avoid borders and grid lines.
        """
        if frame is None or frame.size == 0:
            return None
        x, y, w, h = square.bounds
        off_x = max(4, int(w * 0.08))
        off_y = max(4, int(h * 0.08))

        # 5x5 patch coordinates
        x1 = x + off_x
        y1 = y + off_y
        x2 = x1 + 5
        y2 = y1 + 5

        fh, fw = frame.shape[:2]
        if x1 < 0 or y1 < 0 or x2 > fw or y2 > fh:
            return None

        patch = frame[y1:y2, x1:x2]
        if patch.size == 0:
            return None

        return np.mean(patch, axis=(0, 1)).astype(np.float32)

    def scan_frame(self, frame: np.ndarray) -> List[str]:
        """
        Scan all 64 squares and return the list of square names whose
        top-left corner color deviates from normal background (i.e. is highlighted).
        """
        if not self.is_calibrated or frame is None or frame.size == 0 or not self.board_tracker.squares:
            return []

        highlighted: List[str] = []
        highlight_colors: List[np.ndarray] = []

        for name, sq in self.board_tracker.squares.items():
            color = self.get_corner_color(frame, sq)
            if color is None:
                continue

            is_light = (sq.col + sq.row) % 2 == 0
            expected = self.light_bg_bgr if is_light else self.dark_bg_bgr

            dist = float(np.linalg.norm(color - expected))
            if dist > self.threshold:
                highlighted.append(name)
                highlight_colors.append(color)

        if len(highlighted) == 2 and highlight_colors:
            # Update/refine highlight background color
            self.highlight_bg_bgr = np.median(highlight_colors, axis=0).astype(np.float32)

        return highlighted

    def scan_frame_details(self, frame: np.ndarray) -> Dict[str, dict]:
        """Detailed per-square diagnostic info."""
        if not self.is_calibrated or frame is None or not self.board_tracker.squares:
            return {}

        details = {}
        for name, sq in self.board_tracker.squares.items():
            color = self.get_corner_color(frame, sq)
            if color is None:
                continue
            is_light = (sq.col + sq.row) % 2 == 0
            expected = self.light_bg_bgr if is_light else self.dark_bg_bgr
            dist = float(np.linalg.norm(color - expected)) if expected is not None else 0.0
            is_highlighted = dist > self.threshold
            details[name] = {
                "isLight": is_light,
                "color": [round(float(c), 1) for c in color],
                "dist": round(dist, 2),
                "isHighlighted": is_highlighted,
            }
        return details
