"""
occupancy_detector.py – Square occupancy and visual difference detector (Phase 3).

Prioritizes fast, robust empty vs. occupied square detection:
  - Background baseline modeling (light vs dark squares)
  - Foreground contrast, pixel difference, and edge variance analysis
  - Piece color estimation (White / Black / Unknown)
  - Temporal filtering across consecutive frames (filters out cursor / piece-drag animations)
  - Normalized square crop extraction (64x64) for ML dataset collection and debugging
"""

import logging
from typing import Dict, Any, Optional, Tuple, List
import numpy as np
import cv2

log = logging.getLogger(__name__)


class SquareObservation:
    """Observation for a single square in a specific frame."""

    def __init__(
        self,
        name: str,
        status: str,              # 'EMPTY', 'OCCUPIED', 'UNKNOWN'
        color: str,               # 'WHITE', 'BLACK', 'UNKNOWN'
        confidence: float,        # 0.0 to 1.0
        diff_score: float,        # Visual difference score
        is_stable: bool = True,   # Stability across consecutive frames
        appearance: Tuple[float, ...] = (),
        foreground_coverage: float = 0.0,
    ) -> None:
        self.name = name
        self.status = status
        self.color = color
        self.confidence = float(confidence)
        self.diff_score = float(diff_score)
        self.is_stable = is_stable
        self.appearance = appearance
        self.foreground_coverage = float(foreground_coverage)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "color": self.color,
            "confidence": round(self.confidence, 3),
            "diffScore": round(self.diff_score, 3),
            "isStable": self.is_stable,
            "appearance": [round(value, 2) for value in self.appearance],
            "foregroundCoverage": round(self.foreground_coverage, 3),
        }


class SquareOccupancyDetector:
    """
    Analyzes visual appearance of the 64 squares from locked chessboard coordinates.
    """

    def __init__(
        self,
        board_tracker,
        stability_history_len: int = 3,
        occupied_diff_threshold: float = 14.0,
    ) -> None:
        self.board_tracker = board_tracker
        self.stability_history_len = stability_history_len
        self.occupied_diff_threshold = occupied_diff_threshold

        # Baseline background colors (BGR means for light and dark squares)
        # Defaults to generic light / dark chessboard values until calibrated
        self.light_bg_bgr = np.array([210.0, 210.0, 210.0], dtype=np.float32)
        self.dark_bg_bgr = np.array([120.0, 120.0, 120.0], dtype=np.float32)
        self.is_calibrated = False

        # Observation history for temporal filtering: square_name -> list of status strings
        self._history: Dict[str, List[str]] = {}
        self._last_observations: Dict[str, SquareObservation] = {}

    @property
    def last_observations(self) -> Dict[str, SquareObservation]:
        return self._last_observations

    def get_last_observation(self, square_name: str) -> Optional[SquareObservation]:
        return self._last_observations.get(square_name)

    def calibrate_baseline(self, frame: np.ndarray) -> bool:
        """
        Learn background colors from center squares (rows 2-5) which are ALWAYS empty
        at game start (standard chess position). Sample directly – no piece filtering needed.
        Works for any board theme: white/pink, brown, green, etc.
        """
        if frame is None or frame.size == 0 or not self.board_tracker.squares:
            return False

        light_samples: List[np.ndarray] = []
        dark_samples: List[np.ndarray] = []

        # Center squares (ranks 3-6, rows 2-5) – always empty at game start
        center_squares = [sq for sq in self.board_tracker.squares.values() if 2 <= sq.row <= 5]
        # Rows 3-4 (innermost) are most likely empty, sample them first
        center_squares.sort(key=lambda s: abs(s.row - 3.5))

        for sq in center_squares:
            patch = self._extract_inner_patch(frame, sq.bounds, margin_ratio=0.20)
            if patch is None or patch.size == 0:
                continue
            # Sample the median BGR color of the whole inner patch.
            # No gray filtering – these squares are empty so all pixels are background.
            flat = patch.reshape(-1, 3)
            if flat.shape[0] < 4:
                continue
            sample = np.median(flat, axis=0)
            is_light = (sq.col + sq.row) % 2 == 0
            if is_light:
                light_samples.append(sample)
            else:
                dark_samples.append(sample)

        # Fallback: use the outermost pixel ring of all squares (piece bodies don't reach the edge)
        if not light_samples or not dark_samples:
            for sq in self.board_tracker.squares.values():
                patch = self._extract_background_ring(frame, sq.bounds)
                if patch is not None and patch.size > 0:
                    flat = patch.reshape(-1, 3) if patch.ndim == 3 else patch.reshape(-1, 1)
                    if flat.shape[0] < 4:
                        continue
                    sample = np.median(flat, axis=0)
                    is_light = (sq.col + sq.row) % 2 == 0
                    if is_light and not light_samples:
                        light_samples.append(sample)
                    elif not is_light and not dark_samples:
                        dark_samples.append(sample)

        if light_samples and dark_samples:
            self.light_bg_bgr = np.median(light_samples, axis=0).astype(np.float32)
            self.dark_bg_bgr = np.median(dark_samples, axis=0).astype(np.float32)
            self.is_calibrated = True
            log.info("Occupancy baseline calibrated: Light=%s Dark=%s",
                     np.round(self.light_bg_bgr, 1), np.round(self.dark_bg_bgr, 1))
            return True

        return False

    def process_frame(self, frame: np.ndarray) -> Dict[str, SquareObservation]:
        """
        Evaluate all 64 squares on the provided frame and update stability history.
        """
        if frame is None or frame.size == 0 or not self.board_tracker.squares:
            return {}

        results: Dict[str, SquareObservation] = {}

        for sq in self.board_tracker.squares.values():
            obs = self._evaluate_square(frame, sq)
            results[sq.name] = obs

            # Update temporal filtering history
            if sq.name not in self._history:
                self._history[sq.name] = []
            self._history[sq.name].append(obs.status)
            if len(self._history[sq.name]) > self.stability_history_len:
                self._history[sq.name].pop(0)

            # Check stability (all recent observations agree)
            recent = self._history[sq.name]
            obs.is_stable = len(recent) >= 2 and all(s == recent[0] for s in recent)

        self._last_observations = results
        return results

    def extract_square_crop(
        self, frame: np.ndarray, square_name: str, crop_size: int = 64
    ) -> Optional[np.ndarray]:
        """
        Extract normalized BGR square image crop (e.g. 64x64) for debugging or dataset collection.
        """
        sq = self.board_tracker.get_square(square_name)
        if sq is None or frame is None or frame.size == 0:
            return None

        x, y, w, h = sq.bounds
        fh, fw = frame.shape[:2]
        x1 = max(0, x)
        y1 = max(0, y)
        x2 = min(fw, x + w)
        y2 = min(fh, y + h)

        if x2 <= x1 or y2 <= y1:
            return None

        crop = frame[y1:y2, x1:x2]
        if crop.shape[0] != crop_size or crop.shape[1] != crop_size:
            crop = cv2.resize(crop, (crop_size, crop_size), interpolation=cv2.INTER_AREA)

        return crop

    def get_summary(self) -> Dict[str, Any]:
        """Summary statistics of the latest observations."""
        if not self._last_observations:
            return {"total": 0, "occupied": 0, "empty": 0, "stable": 0, "changing": 0}

        occupied_count = sum(1 for o in self._last_observations.values() if o.status == "OCCUPIED")
        empty_count = sum(1 for o in self._last_observations.values() if o.status == "EMPTY")
        stable_count = sum(1 for o in self._last_observations.values() if o.is_stable)
        changing_count = len(self._last_observations) - stable_count

        return {
            "total": len(self._last_observations),
            "occupied": occupied_count,
            "empty": empty_count,
            "stable": stable_count,
            "changing": changing_count,
            "isCalibrated": self.is_calibrated,
        }

    def _evaluate_square(self, frame: np.ndarray, sq) -> SquareObservation:
        """
        Relative-contrast + achromatic piece detection.

        Works for any board theme (white/pink, brown, green) by comparing pixels
        to the CALIBRATED background color instead of absolute brightness thresholds.

        Strategy:
          1. foreground = euclidean_dist_from_bg >= 20  AND  channel_spread <= 50
             (channel_spread filters out colored highlights / move markers / cursors)
          2. BLACK piece  = foreground AND gray <= 100  (dark charcoal)
          3. WHITE piece  = foreground AND gray >  100  (gray-white pieces)

        The gray <= 100 / > 100 split cleanly separates dark-gray charcoal pieces
        from light-gray white pieces regardless of the board theme.
        """
        patch = self._extract_inner_patch(frame, sq.bounds, margin_ratio=0.12)
        if patch is None or patch.size == 0:
            return SquareObservation(sq.name, "UNKNOWN", "UNKNOWN", 0.0, 0.0, False)

        b = patch[:, :, 0].astype(np.float32)
        g = patch[:, :, 1].astype(np.float32)
        r = patch[:, :, 2].astype(np.float32)

        # Grayscale luminance (BT.601)
        gray = 0.114 * b + 0.587 * g + 0.299 * r

        # Channel spread: 0 for achromatic (gray/white/black), high for colored pixels
        max_ch = np.maximum.reduce([b, g, r])
        min_ch = np.minimum.reduce([b, g, r])
        channel_spread = max_ch - min_ch

        # Euclidean BGR distance from calibrated background color
        is_light_square = (sq.col + sq.row) % 2 == 0
        bg_color = self.light_bg_bgr if is_light_square else self.dark_bg_bgr
        diff_b = b - bg_color[0]
        diff_g = g - bg_color[1]
        diff_r = r - bg_color[2]
        color_diff = np.sqrt(diff_b * diff_b + diff_g * diff_g + diff_r * diff_r)

        # Foreground: different from bg AND achromatic (real piece, not cursor/highlight)
        foreground = (color_diff >= 20.0) & (channel_spread <= 55.0)

        # Black chess piece: dark foreground (charcoal gray)
        black_mask = foreground & (gray <= 100.0)
        # White/gray chess piece: lighter foreground (medium gray – NOT pure white,
        # since real "white" pieces on this theme are rendered in gray)
        white_mask = foreground & (gray > 100.0)

        # Connected component analysis
        num_b_cc, _, stats_b, _ = cv2.connectedComponentsWithStats(black_mask.astype(np.uint8))
        max_black_blob = max([stats_b[i, cv2.CC_STAT_AREA] for i in range(1, num_b_cc)], default=0)

        num_w_cc, _, stats_w, _ = cv2.connectedComponentsWithStats(white_mask.astype(np.uint8))
        max_white_blob = max([stats_w[i, cv2.CC_STAT_AREA] for i in range(1, num_w_cc)], default=0)

        patch_pixels = patch.shape[0] * patch.shape[1]
        # Require at least 4% of inner patch pixels to form a piece blob
        min_piece_blob = max(35, int(patch_pixels * 0.04))

        # BLACK first (more distinct / unambiguous signature)
        if max_black_blob >= min_piece_blob:
            status = "OCCUPIED"
            piece_color = "BLACK"
            confidence = min(1.0, 0.75 + max_black_blob / float(patch_pixels))
            diff_score = float(max_black_blob)
        elif max_white_blob >= min_piece_blob:
            status = "OCCUPIED"
            piece_color = "WHITE"
            confidence = min(1.0, 0.70 + max_white_blob / float(patch_pixels))
            diff_score = float(max_white_blob)
        else:
            status = "EMPTY"
            piece_color = "UNKNOWN"
            confidence = 0.95
            diff_score = 0.0

        std_dev = float(np.std(gray))
        return SquareObservation(
            name=sq.name,
            status=status,
            color=piece_color,
            confidence=confidence,
            diff_score=diff_score,
            appearance=tuple(float(v) for v in (*np.mean(patch, axis=(0, 1)), std_dev, float(max_white_blob))),
            foreground_coverage=float((max_black_blob + max_white_blob) / float(patch_pixels)),
        )

    def get_extreme_ink_counts(self, frame: np.ndarray, sq) -> Tuple[float, float]:
        """
        Return (white_ink, black_ink) blob fractions for team-assignment on R press.
        Uses same relative-contrast + achromatic logic as _evaluate_square.
        Returns (white_fraction, 0) if white piece found, (0, black_fraction) if black,
        (0, 0) if empty.
        """
        patch = self._extract_inner_patch(frame, sq.bounds, margin_ratio=0.12)
        if patch is None or patch.size == 0:
            return 0.0, 0.0

        b = patch[:, :, 0].astype(np.float32)
        g = patch[:, :, 1].astype(np.float32)
        r = patch[:, :, 2].astype(np.float32)

        gray = 0.114 * b + 0.587 * g + 0.299 * r
        max_ch = np.maximum.reduce([b, g, r])
        min_ch = np.minimum.reduce([b, g, r])
        channel_spread = max_ch - min_ch

        is_light = (sq.col + sq.row) % 2 == 0
        bg_color = self.light_bg_bgr if is_light else self.dark_bg_bgr
        diff_b = b - bg_color[0]
        diff_g = g - bg_color[1]
        diff_r = r - bg_color[2]
        color_diff = np.sqrt(diff_b * diff_b + diff_g * diff_g + diff_r * diff_r)

        foreground = (color_diff >= 20.0) & (channel_spread <= 55.0)
        black_mask = foreground & (gray <= 100.0)
        white_mask = foreground & (gray > 100.0)

        num_b_cc, _, stats_b, _ = cv2.connectedComponentsWithStats(black_mask.astype(np.uint8))
        max_black = max([stats_b[i, cv2.CC_STAT_AREA] for i in range(1, num_b_cc)], default=0)

        num_w_cc, _, stats_w, _ = cv2.connectedComponentsWithStats(white_mask.astype(np.uint8))
        max_white = max([stats_w[i, cv2.CC_STAT_AREA] for i in range(1, num_w_cc)], default=0)

        patch_pixels = patch.shape[0] * patch.shape[1]
        min_blob = max(35, int(patch_pixels * 0.04))

        if max_black >= min_blob:
            return 0.0, float(max_black / float(patch_pixels))   # (white_ink, black_ink)
        if max_white >= min_blob:
            return float(max_white / float(patch_pixels)), 0.0   # (white_ink, black_ink)
        return 0.0, 0.0

    def _estimate_piece_color(self, gray_patch: np.ndarray, color_diff: np.ndarray, bg_color: np.ndarray) -> str:
        """Classify foreground relative to its actual square, never absolute screen brightness."""
        foreground = gray_patch[color_diff > 18.0]
        if foreground.size == 0:
            return "UNKNOWN"
        background_luma = float(np.mean(bg_color))
        contrast = float(np.mean(foreground) - background_luma)
        if contrast > 5.0:
            return "WHITE"
        if contrast < -5.0:
            return "BLACK"
        return "UNKNOWN"

    @staticmethod
    def _extract_inner_patch(frame: np.ndarray, bounds: Tuple[int, int, int, int], margin_ratio: float = 0.20):
        """Extract inner patch of square excluding edges."""
        bx, by, bw, bh = bounds
        fh, fw = frame.shape[:2]

        mx = int(bw * margin_ratio)
        my = int(bh * margin_ratio)

        x1 = max(0, bx + mx)
        y1 = max(0, by + my)
        x2 = min(fw, bx + bw - mx)
        y2 = min(fh, by + bh - my)

        if x2 <= x1 or y2 <= y1:
            return None
        return frame[y1:y2, x1:x2]

    @staticmethod
    def _extract_background_ring(frame: np.ndarray, bounds: Tuple[int, int, int, int]):
        """Use a thin edge ring, where pieces and move markers rarely appear."""
        patch = SquareOccupancyDetector._extract_inner_patch(frame, bounds, margin_ratio=0.06)
        if patch is None or patch.size == 0:
            return None
        h, w = patch.shape[:2]
        band = max(2, int(min(w, h) * 0.16))
        mask = np.zeros((h, w), dtype=bool)
        mask[:band, :] = True
        mask[-band:, :] = True
        mask[:, :band] = True
        mask[:, -band:] = True
        return patch[mask]
