"""
protocol.py – IPC helpers for the Python backend.

stdout → Electron: line-delimited JSON (one message per line, no extra output).
stdin  ← Electron: line-delimited JSON commands.

All logging goes to stderr, never to stdout.
"""

import sys
import json
import logging
from typing import Iterator, TextIO

log = logging.getLogger(__name__)


class MessageWriter:
    """Thread-safe, stdout-only JSON message emitter."""

    def __init__(self, stream: TextIO) -> None:
        import threading
        self._stream = stream
        self._lock = threading.Lock()

    def send(self, msg: dict) -> None:
        """Serialize msg to one JSON line on stdout."""
        if "type" not in msg:
            log.error("Attempted to send message without 'type' field: %s", msg)
            return
        line = json.dumps(msg, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            try:
                self._stream.write(line + "\n")
                self._stream.flush()
            except BrokenPipeError:
                log.warning("Broken pipe – Electron receiver may have closed.")
            except Exception as exc:
                log.error("Failed to write message: %s", exc)

    def ack(self, command_id: str) -> None:
        self.send({"type": "ack", "commandId": command_id})

    def error(self, code: str, message: str, detail: str = "") -> None:
        payload = {"type": "error", "code": code, "message": message}
        if detail:
            payload["detail"] = detail
        self.send(payload)


def read_commands(stream: TextIO) -> Iterator[dict]:
    """
    Generator that yields parsed command dicts from a line-delimited JSON stream.

    Stops on EOF or when the stream closes. Invalid lines are logged and skipped.
    """
    for raw in stream:
        line = raw.strip()
        if not line:
            continue
        try:
            cmd = json.loads(line)
        except json.JSONDecodeError as exc:
            log.error("Failed to parse command line: %s  – %s", line[:120], exc)
            continue

        if not isinstance(cmd, dict):
            log.error("Command is not a JSON object: %s", line[:80])
            continue

        if "type" not in cmd:
            log.error("Command missing 'type' field: %s", line[:80])
            continue

        if "commandId" not in cmd:
            # Commands without an ID are unusual but we tolerate them.
            cmd.setdefault("commandId", "")

        yield cmd
