"""
board_tracker.py – Chessboard tracking & 64-square coordinate mapping (Phase 2).

Maintains:
  - Application state machine:
      NO_BOARD -> SEARCHING -> CANDIDATE_FOUND -> BOARD_LOCKED -> TRACKING -> REACQUIRING -> ERROR
  - 64-square coordinate mapping (relative, image, screen, overlay)
  - Algebraic naming ('a1'..'h8') for 'white_bottom' and 'black_bottom' orientations
  - Lightweight frame-to-frame template tracking & drift correction
  - Loss-of-tracking safety checks (pauses events when tracking is lost)
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
import numpy as np
import cv2

log = logging.getLogger(__name__)


class SquareGeometry:
    """Detailed geometric coordinates for a single square on the board."""

    def __init__(
        self,
        name: str,
        col: int,
        row: int,
        board_center: Tuple[float, float],
        image_center: Tuple[float, float],
        screen_center: Tuple[float, float],
        bounds: Tuple[int, int, int, int],  # (x, y, w, h) in image coords
    ) -> None:
        self.name = name
        self.col = col
        self.row = row
        self.board_center = board_center
        self.image_center = image_center
        self.screen_center = screen_center
        self.bounds = bounds

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "col": self.col,
            "row": self.row,
            "boardCenter": {"x": round(self.board_center[0], 4), "y": round(self.board_center[1], 4)},
            "imageCenter": {"x": round(self.image_center[0], 1), "y": round(self.image_center[1], 1)},
            "screenCenter": {"x": round(self.screen_center[0], 1), "y": round(self.screen_center[1], 1)},
            "bounds": {
                "x": self.bounds[0],
                "y": self.bounds[1],
                "width": self.bounds[2],
                "height": self.bounds[3],
            },
        }


class BoardTracker:
    """
    Manages the lifecycle of the chessboard:
    locking, tracking, grid computation, and coordinate mapping.
    """

    def __init__(
        self,
        monitor_offset: Tuple[int, int] = (0, 0),
        dpi_scale: float = 1.0,
        orientation: str = "white_bottom",
    ) -> None:
        self.monitor_offset = monitor_offset  # (screen_left, screen_top)
        self.dpi_scale = dpi_scale
        self.orientation = orientation  # "white_bottom" or "black_bottom"

        # State
        self.state: str = "NO_BOARD"
        self.rect: Optional[Tuple[int, int, int, int]] = None  # (x, y, w, h) in image pixels
        self.squares: Dict[str, SquareGeometry] = {}

        # Template for tracking
        self._tracking_template: Optional[np.ndarray] = None
        self._last_confidence: float = 1.0

    def set_orientation(self, orientation: str) -> None:
        """Update orientation ('white_bottom' or 'black_bottom') and recalculate squares."""
        if orientation in ("white_bottom", "black_bottom"):
            self.orientation = orientation
            if self.rect:
                self._calculate_squares()

    def set_monitor_offset(self, offset: Tuple[int, int], dpi_scale: float = 1.0) -> None:
        """Update screen origin and DPI scaling."""
        self.monitor_offset = offset
        self.dpi_scale = dpi_scale
        if self.rect:
            self._calculate_squares()

    def lock_board(
        self,
        rect: Tuple[int, int, int, int],
        current_frame: Optional[np.ndarray] = None,
        orientation: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Lock onto a board rectangle. Computes all 64 square coordinates.
        Initializes tracking template if current frame is provided.
        """
        x, y, w, h = rect
        if w < 50 or h < 50:
            raise ValueError(f"Invalid board dimensions: {w}x{h}")

        self.rect = (int(x), int(y), int(w), int(h))
        if orientation:
            self.orientation = orientation

        self._calculate_squares()

        if current_frame is not None and current_frame.size > 0:
            self._init_tracking_template(current_frame)

        self.state = "BOARD_LOCKED"
        log.info("Board locked at (%d, %d, %d, %d) with orientation %s", x, y, w, h, self.orientation)
        return self.get_board_info()

    def unlock_board(self) -> None:
        """Unlock and clear board coordinates."""
        self.rect = None
        self.squares = {}
        self._tracking_template = None
        self.state = "NO_BOARD"
        log.info("Board unlocked")

    def track_frame(self, frame: np.ndarray) -> str:
        """
        Lightweight frame-to-frame tracker.
        Searches around the last known board bounding box.
        Returns the updated state ('TRACKING', 'REACQUIRING', etc.).
        """
        if self.rect is None or self._tracking_template is None:
            return self.state

        x, y, w, h = self.rect
        fh, fw = frame.shape[:2]

        # Search window around current rectangle (expand by 15% in all directions)
        margin_x = int(w * 0.15)
        margin_y = int(h * 0.15)

        sx1 = max(0, x - margin_x)
        sy1 = max(0, y - margin_y)
        sx2 = min(fw, x + w + margin_x)
        sy2 = min(fh, y + h + margin_y)

        search_roi = frame[sy1:sy2, sx1:sx2]
        if search_roi.shape[0] < h or search_roi.shape[1] < w:
            self.state = "REACQUIRING"
            return self.state

        # Convert to gray for fast matchTemplate
        if len(search_roi.shape) == 3:
            search_gray = cv2.cvtColor(search_roi, cv2.COLOR_BGR2GRAY)
        else:
            search_gray = search_roi

        # Downsample both template and ROI by 2x for high performance (~1ms)
        small_roi = cv2.resize(search_gray, (search_gray.shape[1] // 2, search_gray.shape[0] // 2))
        small_tmpl = cv2.resize(self._tracking_template, (w // 2, h // 2))

        res = cv2.matchTemplate(small_roi, small_tmpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)

        self._last_confidence = float(max_val)

        # Confidence threshold for reliable tracking
        if max_val >= 0.70:
            # Map back from small scale
            dx = max_loc[0] * 2
            dy = max_loc[1] * 2
            new_x = sx1 + dx
            new_y = sy1 + dy

            # If position drifted, update smoothly
            if abs(new_x - x) > 1 or abs(new_y - y) > 1:
                self.rect = (new_x, new_y, w, h)
                self._calculate_squares()

            self.state = "TRACKING"
        elif max_val < 0.45:
            # Only mark tracking lost if window is minimized or blank (std < 8)
            if np.std(search_roi) < 8.0:
                if self.state != "REACQUIRING":
                    log.warning("Board tracking lost (blank window, confidence: %.2f)", max_val)
                    self.state = "REACQUIRING"
            else:
                # Pieces on the board moved; retain locked coordinates
                self.state = "TRACKING"
        else:
            # Intermediate confidence: retain previous coordinates, keep tracking
            self.state = "TRACKING"

        return self.state

    def get_square(self, name: str) -> Optional[SquareGeometry]:
        return self.squares.get(name.lower())

    def get_board_info(self) -> Dict[str, Any]:
        """Return serialized board metadata including all 64 squares."""
        if self.rect is None:
            return {"state": self.state, "isLocked": False}

        x, y, w, h = self.rect
        return {
            "state": self.state,
            "isLocked": True,
            "rect": {
                "left": x,
                "top": y,
                "width": w,
                "height": h,
                "screenLeft": int(x + self.monitor_offset[0]),
                "screenTop": int(y + self.monitor_offset[1]),
            },
            "orientation": self.orientation,
            "squareWidth": round(w / 8.0, 2),
            "squareHeight": round(h / 8.0, 2),
            "trackingConfidence": round(self._last_confidence, 2),
            "squares": [sq.to_dict() for sq in self.squares.values()],
        }

    def _init_tracking_template(self, frame: np.ndarray) -> None:
        """Create reference template from locked board region."""
        x, y, w, h = self.rect  # type: ignore
        fh, fw = frame.shape[:2]
        x1 = max(0, x)
        y1 = max(0, y)
        x2 = min(fw, x + w)
        y2 = min(fh, y + h)

        roi = frame[y1:y2, x1:x2]
        if len(roi.shape) == 3:
            self._tracking_template = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        else:
            self._tracking_template = roi.copy()

    def _calculate_squares(self) -> None:
        """Compute the 64-square grid geometry and coordinate mappings."""
        if self.rect is None:
            return

        bx, by, bw, bh = self.rect
        sq_w = bw / 8.0
        sq_h = bh / 8.0

        mon_x, mon_y = self.monitor_offset
        self.squares = {}

        for row in range(8):
            for col in range(8):
                # Calculate algebraic name based on orientation
                if self.orientation == "white_bottom":
                    file_char = chr(ord('a') + col)
                    rank_char = str(8 - row)
                else:
                    file_char = chr(ord('h') - col)
                    rank_char = str(row + 1)

                sq_name = f"{file_char}{rank_char}"

                # Relative center in [0.0, 1.0]
                rel_cx = (col + 0.5) / 8.0
                rel_cy = (row + 0.5) / 8.0

                # Captured image pixel coordinates
                img_cx = bx + (col + 0.5) * sq_w
                img_cy = by + (row + 0.5) * sq_h

                # Desktop screen pixel coordinates (including monitor offset)
                screen_cx = mon_x + img_cx
                screen_cy = mon_y + img_cy

                # Bounding box of the square inside captured image
                sq_x = int(bx + col * sq_w)
                sq_y = int(by + row * sq_h)
                sq_width = int(sq_w)
                sq_height = int(sq_h)

                sq_geo = SquareGeometry(
                    name=sq_name,
                    col=col,
                    row=row,
                    board_center=(rel_cx, rel_cy),
                    image_center=(img_cx, img_cy),
                    screen_center=(screen_cx, screen_cy),
                    bounds=(sq_x, sq_y, sq_width, sq_height),
                )
                self.squares[sq_name] = sq_geo
