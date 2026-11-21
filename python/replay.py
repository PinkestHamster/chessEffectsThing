"""Phase 5 replay runner and accuracy metrics for recorded board-frame manifests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

import cv2

from board_tracker import BoardTracker
from move_classifier import MoveClassifier
from occupancy_detector import SquareOccupancyDetector


class AccuracyMetrics:
    def __init__(self) -> None:
        self.board_frames = self.board_hits = 0
        self.occupancy_total = self.occupancy_correct = 0
        self.expected_captures: set[tuple[str, str, str]] = set()
        self.actual_captures: set[tuple[str, str, str]] = set()

    def report(self) -> Dict[str, float | int]:
        matched = len(self.expected_captures & self.actual_captures)
        false_positives = len(self.actual_captures - self.expected_captures)
        return {
            "boardDetectionRate": self.board_hits / self.board_frames if self.board_frames else 0.0,
            "occupancyAccuracy": self.occupancy_correct / self.occupancy_total if self.occupancy_total else 0.0,
            "capturePrecision": matched / len(self.actual_captures) if self.actual_captures else 0.0,
            "captureRecall": matched / len(self.expected_captures) if self.expected_captures else 0.0,
            "falsePositiveRate": false_positives / len(self.actual_captures) if self.actual_captures else 0.0,
            "expectedCaptures": len(self.expected_captures),
            "actualCaptures": len(self.actual_captures),
        }


def run_replay(manifest_path: str | Path) -> Dict[str, float | int]:
    path = Path(manifest_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    board = manifest["board"]
    tracker = BoardTracker()
    tracker.lock_board((board["left"], board["top"], board["width"], board["height"]), orientation=board.get("orientation", "white_bottom"))
    detector, classifier, metrics = SquareOccupancyDetector(tracker), MoveClassifier(), AccuracyMetrics()

    for item in manifest.get("frames", []):
        frame = cv2.imread(str((path.parent / item["path"]).resolve()))
        if frame is None:
            continue
        metrics.board_frames += 1
        metrics.board_hits += 1
        if not detector.is_calibrated:
            detector.calibrate_baseline(frame)
        observations = detector.process_frame(frame)
        for square, expected in item.get("occupancy", {}).items():
            if square in observations:
                metrics.occupancy_total += 1
                metrics.occupancy_correct += observations[square].status == expected
        decision = classifier.process(observations)
        if decision and decision.is_capture:
            metrics.actual_captures.add((decision.source_square, decision.destination_square, decision.captured_square or ""))
        for event in item.get("expectedCaptures", []):
            metrics.expected_captures.add((event["sourceSquare"], event["destinationSquare"], event.get("capturedSquare", event["destinationSquare"])))
    return metrics.report()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate a recorded Chess Vision FX replay manifest")
    parser.add_argument("manifest")
    args = parser.parse_args()
    print(json.dumps(run_replay(args.manifest), indent=2))
