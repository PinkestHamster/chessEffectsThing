# Chess Vision FX

Cosmetic desktop companion app providing real-time visual particle effects and detection for online chess (Chess.com, Lichess, etc.).

---

## 🎮 Shortcut Controls

When the app is in **Active Mode** (toggled with `]`):

| Key | Action | Description |
|---|---|---|
| `]` | **Toggle Active / Inactive** | Master toggle for visual effects and global game shortcuts. When inactive, hotkeys pass through freely to your browser/system. |
| `[` | **Find Board Only** | Scans the screen, locks board coordinates, calibrates colors/orientations, and arms the real-time pixel scanner. Does **not** force standard opening pieces. |
| `R` | **Reset Pieces Position** | Resets the virtual board to the standard 16 vs 16 opening setup on the currently locked board. |
| `F` | **Toggle Debug Overlay** | Shows/hides the on-screen square and piece labels overlay for debugging. |

---

## 🚀 Periodic Board Scan & Auto-Correction Pipeline Plan

### Overview & Goal
Currently, the application tracks moves via ultra-low-latency corner pixel delta scanning (~2-5ms) assuming standard starting piece positions. 

To support **arbitrary starting positions** (mid-game setups, puzzles, analysis boards) and to **auto-correct any desyncs or missed moves without user intervention**, we are adding a background **Periodic Board Scan** loop.

The fast movement scanner will continue running completely unblocked, while the periodic image scanner quietly verifies and reconciles the internal board position.

```
┌────────────────────────────────────────────────────────┐
│               ⚡ Fast Real-Time Loop (30–60 FPS)       │
│  Screen Capture ──► Corner Pixel Delta ──► Move FX     │
└──────────────────────────┬─────────────────────────────┘
                           │ (Never blocked)
                           ▼
┌────────────────────────────────────────────────────────┐
│             🔍 Periodic Board Scan (Every 1.5–3.0s)    │
│  Board Quiescence Check                                │
│       │                                                │
│       ▼                                                │
│  Board Tile Crop (64 Squares)                          │
│       │                                                │
│       ▼                                                │
│  Piece Classifier (Occupancy + Piece Type)             │
│       │                                                │
│       ▼                                                │
│  State Reconciliation Engine (Debounced Diff)          │
│       │                                                │
│       ▼                                                │
│  Silent Internal VirtualBoard Correction               │
└────────────────────────────────────────────────────────┘
```

---

### Key Architectural Pillars

### 1. Dual-Loop Concurrency Model
- **Fast Loop (Untouched)**:
  - `pixel_scanner.py` + `ScreenCapturer` runs continuously at 30–60 FPS.
  - Handles immediate visual feedback (explosions, move indicators) in < 5ms.
- **Slow Loop (Background Worker)**:
  - Runs in a dedicated worker thread (`PeriodicScannerWorker`).
  - Completely non-blocking—ensures zero frame hitching or GIL contention.
  - Samples a full-resolution board crop every 1.5 to 3.0 seconds.

### 2. Motion Quiescence & Stability Filter
- Pieces in mid-drag or during fast animation have motion blur or cursor overlap.
- The scanner only triggers when the board is **quiescent** (no pixel changes or highlight transitions in the last ~300ms).
- A candidate correction must be confirmed across **2 consecutive scans** before applying, preventing false positives from fleeting mouse gestures.

### 3. Piece Classification Pipeline (`piece_classifier.py`)
Each of the 64 squares is classified using a two-stage process:
- **Stage 1: Fast Ink & Occupancy Filter (OpenCV)**:
  - Measures foreground ink density and contrast against baseline light/dark square colors.
  - Empty squares are skipped instantly (< 0.2ms total for all 64 squares).
- **Stage 2: Piece Classification**:
  - For occupied squares, classifies piece type (`P`, `N`, `B`, `R`, `Q`, `K`):
    - **Method A (Template / Feature Matcher)**: Multi-scale normalized template library for popular web piece sets (Chess.com Neo, Classic, Lichess Cburnett).
    - **Method B (Lightweight ONNX Classifier)**: Compact 2MB quantized CNN running on CPU in batch mode (< 15ms total).

### 4. Non-Destructive State Reconciliation (`reconciliation_engine.py`)
- Standard move detection emits capture FX when pieces disappear. The reconciliation engine must **correct state silently**:
  - Corrects pieces without triggering accidental combat particle explosions.
  - Automatically identifies pawn promotions (e.g., `e7` pawn turns to queen on `e8`).
  - Supports loading into an active game at move 20+ without manual configuration.

---

### 📁 Planned File Structure

```
python/
├── periodic_board_scanner.py  # Background timer & frame grabber
├── piece_classifier.py        # 64-square extraction & piece detection
├── reconciliation_engine.py   # State diffing & non-destructive correction
├── pixel_scanner.py           # Existing real-time fast scanner (kept intact)
├── virtual_board.py           # Virtual board model (updated with reconcile())
└── backend.py                 # Worker orchestration & IPC
```

---

### 🛠 UI Settings (Planned)
- **Auto-Correct Board (Periodic Scan)**: Toggle switch in control panel (Default: ON).
- **Scan Interval Slider**: Adjustable from 1.0s to 5.0s.
- **Piece Set Selector**: Auto-detect or select active piece style.
