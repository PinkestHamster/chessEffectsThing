"""
board_detector.py – Classical OpenCV-based chessboard candidate detector (Phase 2).

Finds 8x8 chessboard candidates from screen images using deterministic computer vision:
  - Grayscale & adaptive preprocessing
  - Contour & polygon approximation
  - Geometric aspect ratio and minimum size scoring
  - Grid line & 8x8 division frequency analysis
  - Alternating square intensity/texture variance scoring
  - Inspectable scoring metrics with rejection reasons
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
import cv2

log = logging.getLogger(__name__)


class BoardCandidate:
    """Represents a scored chessboard candidate region."""

    def __init__(
        self,
        candidate_id: int,
        x: int,
        y: int,
        w: int,
        h: int,
        score: float,
        corners: List[Tuple[int, int]],
        grid_score: float = 0.0,
        aspect_ratio: float = 1.0,
        rejection_reasons: Optional[List[str]] = None,
    ) -> None:
        self.candidate_id = candidate_id
        self.x = int(x)
        self.y = int(y)
        self.w = int(w)
        self.h = int(h)
        self.score = float(score)
        self.corners = corners
        self.grid_score = float(grid_score)
        self.aspect_ratio = float(aspect_ratio)
        self.rejection_reasons = rejection_reasons or []

    @property
    def square_width(self) -> float:
        return self.w / 8.0

    @property
    def square_height(self) -> float:
        return self.h / 8.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.candidate_id,
            "rect": {
                "left": self.x,
                "top": self.y,
                "width": self.w,
                "height": self.h,
            },
            "score": round(self.score, 3),
            "squareWidth": round(self.square_width, 1),
            "squareHeight": round(self.square_height, 1),
            "corners": [[int(pt[0]), int(pt[1])] for pt in self.corners],
            "aspectRatio": round(self.aspect_ratio, 3),
            "gridScore": round(self.grid_score, 3),
            "reasons": self.rejection_reasons,
        }


class BoardDetector:
    """
    Classical detector for chessboards in screen frames.
    """

    def __init__(
        self,
        min_board_size: int = 160,          # Minimum board dimension in pixels
        aspect_tolerance: float = 0.08,     # Allow aspect ratio in [1 - tol, 1 + tol]
        min_confidence_score: float = 0.40,  # Minimum score to accept candidate
    ) -> None:
        self.min_board_size = min_board_size
        self.aspect_tolerance = aspect_tolerance
        self.min_confidence_score = min_confidence_score

    def detect(self, image: np.ndarray) -> List[BoardCandidate]:
        """
        Scan image for chessboard candidates and return scored list sorted descending by score.
        """
        if image is None or image.size == 0:
            return []

        h, w = image.shape[:2]
        if w < self.min_board_size or h < self.min_board_size:
            return []

        # Convert to grayscale
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()

        candidates: List[BoardCandidate] = []
        candidate_id = 0

        # Method 1: Edge and contour hierarchy
        # Use bilateral or Gaussian blur to suppress noise while keeping square edges sharp
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 50, 150)

        # Dilate slightly to close broken boundary lines of the board
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        dilated = cv2.dilate(edges, kernel, iterations=1)

        contours, _ = cv2.findContours(dilated, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

        seen_boxes: List[Tuple[int, int, int, int]] = []

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < (self.min_board_size * self.min_board_size):
                continue

            # Approximate polygonal shape
            peri = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)

            x, y, bw, bh = cv2.boundingRect(approx)

            # Check minimum size
            if bw < self.min_board_size or bh < self.min_board_size:
                continue

            # Check if this box is nearly identical to an already seen box (deduplication)
            if self._is_duplicate((x, y, bw, bh), seen_boxes):
                continue

            candidate = self._evaluate_box(gray, x, y, bw, bh, candidate_id)
            seen_boxes.append((x, y, bw, bh))
            candidate_id += 1

            if candidate.score >= self.min_confidence_score:
                candidates.append(candidate)

        # Method 2: Fallback / multi-threshold adaptive search if no high scoring candidate found
        if not candidates or max((c.score for c in candidates), default=0.0) < 0.60:
            adaptive = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
            )
            contours_adap, _ = cv2.findContours(adaptive, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
            for cnt in contours_adap:
                x, y, bw, bh = cv2.boundingRect(cnt)
                if bw < self.min_board_size or bh < self.min_board_size:
                    continue
                if self._is_duplicate((x, y, bw, bh), seen_boxes):
                    continue

                candidate = self._evaluate_box(gray, x, y, bw, bh, candidate_id)
                seen_boxes.append((x, y, bw, bh))
                candidate_id += 1

                if candidate.score >= self.min_confidence_score:
                    candidates.append(candidate)

        # Sort candidates descending by confidence score
        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates

    def _evaluate_box(
        self, gray: np.ndarray, x: int, y: int, w: int, h: int, candidate_id: int
    ) -> BoardCandidate:
        """Score a rectangular candidate region."""
        rejection_reasons = []

        aspect = float(w) / float(h) if h > 0 else 0.0
        aspect_dev = abs(1.0 - aspect)

        # Aspect ratio score: 1.0 is ideal square
        if aspect_dev > self.aspect_tolerance:
            rejection_reasons.append(f"Aspect ratio {aspect:.2f} deviates from square (tol: ±{self.aspect_tolerance})")
            aspect_score = max(0.0, 1.0 - (aspect_dev * 3.0))
        else:
            aspect_score = 1.0 - aspect_dev

        # Extract ROI
        img_h, img_w = gray.shape[:2]
        x1 = max(0, x)
        y1 = max(0, y)
        x2 = min(img_w, x + w)
        y2 = min(img_h, y + h)

        if (x2 - x1) < self.min_board_size or (y2 - y1) < self.min_board_size:
            rejection_reasons.append("ROI dimensions smaller than minimum board size")
            return BoardCandidate(
                candidate_id=candidate_id,
                x=x, y=y, w=w, h=h,
                score=0.0,
                corners=[(x, y), (x + w, y), (x + w, y + h), (x, y + h)],
                aspect_ratio=aspect,
                rejection_reasons=rejection_reasons,
            )

        roi = gray[y1:y2, x1:x2]

        # Analyze 8x8 alternating grid characteristics
        grid_score, grid_reasons = self._evaluate_8x8_grid(roi)
        rejection_reasons.extend(grid_reasons)

        # Overall composite score
        # 40% aspect ratio, 60% 8x8 alternating grid consistency
        composite_score = (aspect_score * 0.40) + (grid_score * 0.60)

        corners = [
            (x1, y1),
            (x2, y1),
            (x2, y2),
            (x1, y2),
        ]

        return BoardCandidate(
            candidate_id=candidate_id,
            x=x1,
            y=y1,
            w=x2 - x1,
            h=y2 - y1,
            score=composite_score,
            corners=corners,
            grid_score=grid_score,
            aspect_ratio=aspect,
            rejection_reasons=rejection_reasons,
        )

    def _evaluate_8x8_grid(self, roi: np.ndarray) -> Tuple[float, List[str]]:
        """
        Check if ROI contains an 8x8 grid of alternating light/dark squares.
        Returns (grid_score, reasons).
        """
        reasons = []
        rh, rw = roi.shape[:2]
        sq_w = rw / 8.0
        sq_h = rh / 8.0

        # Sample cell center intensities for the 8x8 squares
        cell_means = np.zeros((8, 8), dtype=np.float32)

        for r in range(8):
            for c in range(8):
                # Sample the center 50% of each cell to avoid boundary borders/pieces
                cx1 = int(c * sq_w + 0.25 * sq_w)
                cx2 = int((c + 1) * sq_w - 0.25 * sq_w)
                cy1 = int(r * sq_h + 0.25 * sq_h)
                cy2 = int((r + 1) * sq_h - 0.25 * sq_h)

                cx2 = max(cx1 + 1, cx2)
                cy2 = max(cy1 + 1, cy2)

                cell_patch = roi[cy1:cy2, cx1:cx2]
                cell_means[r, c] = float(np.mean(cell_patch))

        # Check alternating pattern: (r + c) % 2 gives theoretical parity (light vs dark)
        parity_0 = cell_means[np.indices((8, 8)).sum(axis=0) % 2 == 0]
        parity_1 = cell_means[np.indices((8, 8)).sum(axis=0) % 2 == 1]

        mean_0 = float(np.mean(parity_0))
        mean_1 = float(np.mean(parity_1))
        diff = abs(mean_0 - mean_1)

        # Contrast between alternating squares should be discernible (e.g. at least 10-15 grayscale levels)
        if diff < 8.0:
            reasons.append(f"Low alternating contrast between squares ({diff:.1f} levels)")
            contrast_score = max(0.1, diff / 25.0)
        else:
            contrast_score = min(1.0, diff / 40.0)

        # Check internal square variance (uniformity inside cells of same parity)
        std_0 = float(np.std(parity_0))
        std_1 = float(np.std(parity_1))
        avg_std = (std_0 + std_1) / 2.0

        # Pieces on the board increase std, but alternating difference should remain visible
        uniformity_score = max(0.2, 1.0 - min(1.0, avg_std / 70.0))

        # Edge gradients along 7 internal grid dividing lines
        h_lines_score = self._check_internal_grid_lines(roi, horizontal=True)
        v_lines_score = self._check_internal_grid_lines(roi, horizontal=False)
        line_score = (h_lines_score + v_lines_score) / 2.0

        grid_score = (contrast_score * 0.45) + (uniformity_score * 0.25) + (line_score * 0.30)
        return float(grid_score), reasons

    def _check_internal_grid_lines(self, roi: np.ndarray, horizontal: bool) -> float:
        """Check for gradient peaks at the 7 internal grid division boundaries."""
        h, w = roi.shape[:2]
        size = h if horizontal else w
        step = size / 8.0

        if horizontal:
            grad = np.abs(cv2.Sobel(roi, cv2.CV_32F, 0, 1, ksize=3))
            profile = np.mean(grad, axis=1)  # 1D profile along Y
        else:
            grad = np.abs(cv2.Sobel(roi, cv2.CV_32F, 1, 0, ksize=3))
            profile = np.mean(grad, axis=0)  # 1D profile along X

        # Check gradient energy near each of the 7 boundary positions: k * step (k=1..7)
        matched_boundaries = 0
        tolerance_px = max(2, int(step * 0.15))

        for k in range(1, 8):
            expected_pos = int(k * step)
            p_start = max(0, expected_pos - tolerance_px)
            p_end = min(len(profile), expected_pos + tolerance_px + 1)
            window = profile[p_start:p_end]
            if len(window) > 0 and np.max(window) > np.mean(profile) * 1.1:
                matched_boundaries += 1

        return float(matched_boundaries / 7.0)

    @staticmethod
    def _is_duplicate(
        box: Tuple[int, int, int, int], seen_boxes: List[Tuple[int, int, int, int]], threshold: float = 0.85
    ) -> bool:
        """Check if box overlaps significantly with any previously evaluated box (IoU)."""
        x1, y1, w1, h1 = box
        for x2, y2, w2, h2 in seen_boxes:
            ix1 = max(x1, x2)
            iy1 = max(y1, y2)
            ix2 = min(x1 + w1, x2 + w2)
            iy2 = min(y1 + h1, y2 + h2)

            iw = max(0, ix2 - ix1)
            ih = max(0, iy2 - iy1)
            intersection = iw * ih

            area1 = w1 * h1
            area2 = w2 * h2
            union = area1 + area2 - intersection

            if union > 0 and (intersection / union) >= threshold:
                return True
        return False
