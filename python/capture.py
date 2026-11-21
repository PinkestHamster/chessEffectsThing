"""
capture.py – Screen capture module (Phase 1).

Uses `mss` for high-performance desktop capture on Windows.
Handles:
  - Monitor enumeration (with DPI scale factor)
  - Configurable FPS capture loop
  - Frame timestamping and duration measurement
  - JPEG preview encoding for the control window
  - Diagnostic snapshot saving
  - Graceful shutdown without crashes
"""

import sys
import os
import time
import threading
import logging
import json
import base64
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import cv2
import mss
import mss.tools

log = logging.getLogger(__name__)


class ScreenCapturer:
    """
    Captures frames from a selected monitor in a background thread.
    Sends frame_status and frame_preview messages via the MessageWriter.
    """

    def __init__(
        self,
        monitor_index: int,
        target_fps: float,
        send_previews: bool,
        writer,               # protocol.MessageWriter
        debug: bool = False,
    ) -> None:
        self.monitor_index = monitor_index
        self.target_fps = target_fps
        self.send_previews = send_previews
        self.writer = writer
        self.debug = debug

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # Running statistics
        self._frame_count = 0
        self._fps_window: list[float] = []   # timestamps of last N frames
        self._fps_window_size = 10
        self._last_frame: Optional[np.ndarray] = None
        self._last_frame_meta: Optional[dict] = None
        self._tracker = None
        self._occupancy_detector = None
        self._highlight_detector = None
        self._pixel_scanner = None
        self._move_callback = None
        self._last_status_time = 0.0
        self._lock = threading.Lock()

    # ── Public control ─────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            log.warning("Capturer already running")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._capture_loop, daemon=True, name="Capturer")
        self._thread.start()
        log.info("Capturer thread started (monitor=%d, fps=%.1f)", self.monitor_index, self.target_fps)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3.0)
            if self._thread.is_alive():
                log.warning("Capturer thread did not stop in time")
        self._thread = None
        log.info("Capturer stopped")

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def set_fps(self, fps: float) -> None:
        self.target_fps = max(0.5, min(30.0, fps))
        log.info("FPS target updated: %.1f", self.target_fps)

    def get_latest_frame(self) -> Optional[np.ndarray]:
        """Return a copy of the most recently captured BGR frame, or None."""
        with self._lock:
            if self._last_frame is None:
                return None
            return self._last_frame.copy()

    def set_tracker(self, tracker) -> None:
        """Attach a BoardTracker instance for real-time frame tracking."""
        with self._lock:
            self._tracker = tracker

    def set_occupancy_detector(self, detector) -> None:
        """Attach a SquareOccupancyDetector instance for real-time occupancy updates."""
        with self._lock:
            self._occupancy_detector = detector

    def set_highlight_detector(self, detector) -> None:
        """Attach a HighlightDetector instance for corner-based highlight move detection."""
        with self._lock:
            self._highlight_detector = detector

    def set_pixel_scanner(self, scanner) -> None:
        """Attach a PixelScanner instance for ultra-fast pixel movement detection."""
        with self._lock:
            self._pixel_scanner = scanner

    def set_move_callback(self, callback) -> None:
        """Receive stable occupancy observations for Phase 4 classification."""
        with self._lock:
            self._move_callback = callback

    def save_snapshot(self, output_dir: Optional[str] = None) -> Optional[str]:
        """Save a diagnostic snapshot (image + metadata) to disk."""
        with self._lock:
            if self._last_frame is None or self._last_frame_meta is None:
                log.warning("No frame available for snapshot")
                return None
            frame = self._last_frame.copy()
            meta = dict(self._last_frame_meta)

        if output_dir is None:
            output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "snapshots")
        os.makedirs(output_dir, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        img_path  = os.path.join(output_dir, f"snapshot_{ts}.png")
        meta_path = os.path.join(output_dir, f"snapshot_{ts}.json")

        try:
            cv2.imwrite(img_path, frame)
            meta["snapshotImagePath"] = img_path
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
            log.info("Snapshot saved: %s", meta_path)
            return meta_path
        except Exception as exc:
            log.error("Failed to save snapshot: %s", exc)
            return None

    # ── Monitor enumeration ────────────────────────────────────────────────────

    @staticmethod
    def list_monitors() -> list[dict]:
        """Return a list of monitor descriptors usable by both Python and Electron."""
        monitors = []
        try:
            with mss.MSS() as sct:
                # sct.monitors[0] is the "all monitors" virtual monitor; skip it.
                for i, mon in enumerate(sct.monitors[1:]):
                    monitors.append({
                        "index":     i,
                        "left":      mon["left"],
                        "top":       mon["top"],
                        "width":     mon["width"],
                        "height":    mon["height"],
                        "scale":     ScreenCapturer._get_scale_factor(i),
                        "isPrimary": i == 0,   # mss lists primary first
                    })
        except Exception as exc:
            log.error("Failed to enumerate monitors: %s", exc)
        return monitors

    @staticmethod
    def _get_scale_factor(monitor_index: int) -> float:
        """
        Attempt to read the Windows DPI scale factor for a given monitor.
        Falls back to 1.0 if ctypes is unavailable or the call fails.
        """
        try:
            import ctypes
            # GetDpiForMonitor requires Windows 8.1+ (shcore.dll)
            shcore = ctypes.windll.shcore          # type: ignore[attr-defined]
            # Use the monitor index to get an HMONITOR handle via EnumDisplayMonitors.
            # As a simpler approximation, read the primary monitor DPI.
            dpi_x = ctypes.c_uint()
            dpi_y = ctypes.c_uint()
            # MonitorFromPoint for primary (0,0), then GetDpiForMonitor
            user32 = ctypes.windll.user32          # type: ignore[attr-defined]
            hmon = user32.MonitorFromPoint(ctypes.wintypes.POINT(1, 1), 2)  # MONITOR_DEFAULTTOPRIMARY
            shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y))
            return round(dpi_x.value / 96.0, 2)
        except Exception:
            return 1.0

    # ── Capture loop ───────────────────────────────────────────────────────────

    def _capture_loop(self) -> None:
        target_interval = 1.0 / max(self.target_fps, 0.1)

        try:
            with mss.MSS() as sct:
                monitors = sct.monitors
                # monitors[0] = all-screens virtual, monitors[1+] = real monitors
                if self.monitor_index + 1 >= len(monitors):
                    log.error(
                        "Monitor index %d out of range (have %d monitors)",
                        self.monitor_index, len(monitors) - 1,
                    )
                    self.writer.send({
                        "type": "error",
                        "code": "INVALID_MONITOR",
                        "message": f"Monitor {self.monitor_index} does not exist.",
                    })
                    return

                monitor = monitors[self.monitor_index + 1]
                log.info("Capturing monitor %d: %s", self.monitor_index, monitor)

                while not self._stop_event.is_set():
                    loop_start = time.perf_counter()

                    frame, meta = self._capture_single(sct, monitor)

                    if frame is not None and meta is not None:
                        with self._lock:
                            self._last_frame = frame
                            self._last_frame_meta = meta

                        self._frame_count += 1
                        self._update_fps_stats(meta["timestamp"])

                        now = time.monotonic()

                        # Ultra-fast pixel recognition hot loop (when board is locked & pixel scanner initialized)
                        if self._pixel_scanner and self._pixel_scanner.is_initialized:
                            changed_squares = self._pixel_scanner.scan_frame(frame)
                            if changed_squares and self._move_callback:
                                self._move_callback(changed_squares, meta["timestamp"], frame)
                        elif self._tracker and self._tracker.rect is not None:
                            # Pre-initialization fallback only
                            prev_state = self._tracker.state
                            new_state = self._tracker.track_frame(frame)
                            if new_state != prev_state:
                                self.writer.send({
                                    "type": "state_change",
                                    "state": new_state,
                                    "reason": f"Board tracking transitioned to {new_state}",
                                })

                            if self._occupancy_detector:
                                obs = self._occupancy_detector.process_frame(frame)
                                if self._move_callback:
                                    self._move_callback(obs, meta["timestamp"], frame)

                        # Send frame_status and previews (throttled to ~5 Hz during fast scanning)
                        is_fast_scanning = (self._pixel_scanner is not None and self._pixel_scanner.is_initialized)
                        if not is_fast_scanning or (now - self._last_status_time >= 0.2):
                            self._last_status_time = now
                            self.writer.send({
                                "type": "frame_status",
                                "frame": meta
                            })
                            if self.debug and self._pixel_scanner and self._pixel_scanner.is_initialized:
                                self.writer.send({
                                    "type": "move_scan_debug",
                                    "orientation": self._tracker.orientation if self._tracker else "unknown",
                                    "highlights": self._pixel_scanner.last_scan_highlights,
                                    "rawHighlights": self._pixel_scanner.last_scan_raw_highlights,
                                    "targets": self._pixel_scanner.last_scan_targets,
                                    "candidates": self._pixel_scanner.last_highlight_candidates,
                                    "previousHighlights": sorted(self._pixel_scanner._old_highlighted),
                                    "rejectedPair": self._pixel_scanner.last_rejected_pair,
                                })
                            if self._pixel_scanner and self._pixel_scanner.is_initialized:
                                self.writer.send({
                                    "type": "square_scan_status",
                                    "squares": self._pixel_scanner.last_square_status,
                                })
                            if self.send_previews:
                                self._send_preview(frame, meta)

                    # Ultra-fast scanning loop: continuously scan without deliberate sleep when locked
                    if self._pixel_scanner and self._pixel_scanner.is_initialized:
                        continue

                    # Sleep for the remaining interval when not actively scanning locked board
                    elapsed = time.perf_counter() - loop_start
                    sleep_time = target_interval - elapsed
                    if sleep_time > 0:
                        self._stop_event.wait(timeout=sleep_time)

                    # Update interval in case fps was changed externally
                    target_interval = 1.0 / max(self.target_fps, 0.1)

        except Exception as exc:
            log.exception("Capture loop crashed: %s", exc)
            self.writer.send({
                "type": "error",
                "code": "CAPTURE_CRASH",
                "message": f"Capture loop error: {exc}",
            })

    def _capture_single(self, sct: mss.mss, monitor: dict) -> tuple:
        """Grab one frame, return (bgr_ndarray, metadata_dict) or (None, None) on failure."""
        try:
            t_start = time.perf_counter()
            screenshot = sct.grab(monitor)
            t_end = time.perf_counter()

            # mss returns BGRA; convert to BGR for cv2
            frame_bgra = np.frombuffer(screenshot.raw, dtype=np.uint8).reshape(
                screenshot.height, screenshot.width, 4
            )
            frame_bgr = cv2.cvtColor(frame_bgra, cv2.COLOR_BGRA2BGR)

            meta = {
                "timestamp":        datetime.now(timezone.utc).isoformat(),
                "width":            screenshot.width,
                "height":           screenshot.height,
                "captureDurationMs": round((t_end - t_start) * 1000, 2),
                "monitorIndex":     self.monitor_index,
            }
            return frame_bgr, meta

        except Exception as exc:
            log.error("Failed to capture frame: %s", exc)
            return None, None

    def _update_fps_stats(self, timestamp_iso: str) -> None:
        now = time.monotonic()
        self._fps_window.append(now)
        if len(self._fps_window) > self._fps_window_size:
            self._fps_window.pop(0)

    def _compute_avg_fps(self) -> float:
        if len(self._fps_window) < 2:
            return 0.0
        span = self._fps_window[-1] - self._fps_window[0]
        if span <= 0:
            return 0.0
        return (len(self._fps_window) - 1) / span

    def _send_preview(self, frame: np.ndarray, meta: dict) -> None:
        """Encode a downscaled JPEG and send it as a frame_preview message."""
        try:
            # Downscale to max 640-wide for the preview
            h, w = frame.shape[:2]
            max_w = 640
            if w > max_w:
                scale = max_w / w
                new_w = max_w
                new_h = int(h * scale)
                preview = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
            else:
                preview = frame

            # Encode JPEG (quality 60 balances bandwidth vs clarity)
            ok, buf = cv2.imencode(".jpg", preview, [cv2.IMWRITE_JPEG_QUALITY, 60])
            if not ok:
                return

            jpeg_b64 = base64.b64encode(buf.tobytes()).decode("ascii")
            self.writer.send({
                "type": "frame_preview",
                "jpegBase64": jpeg_b64,
                "frame": meta,
            })
        except Exception as exc:
            log.error("Failed to send preview: %s", exc)
