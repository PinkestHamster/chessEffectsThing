"use strict";
/**
 * IPC Protocol – line-delimited JSON messages between Electron main process and Python backend.
 *
 * Python → Electron (stdout, one JSON object per line):
 *   All messages have a "type" discriminant field.
 *
 * Electron → Python (stdin, one JSON object per line):
 *   Commands sent from the control window.
 *
 * Python diagnostic logs go to stderr only.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.nextCommandId = nextCommandId;
// ─── Electron → Python Commands ───────────────────────────────────────────────
/** Unique command IDs for ack tracking */
let _cmdCounter = 0;
function nextCommandId() {
    return `cmd-${++_cmdCounter}`;
}
//# sourceMappingURL=protocol.js.map