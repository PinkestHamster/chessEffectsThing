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

// ─── Application State ───────────────────────────────────────────────────────

export type AppState =
  | 'NO_BOARD'
  | 'SEARCHING'
  | 'CANDIDATE_FOUND'
  | 'BOARD_LOCKED'
  | 'TRACKING'
  | 'REACQUIRING'
  | 'ERROR';

// ─── Monitor Descriptor ───────────────────────────────────────────────────────

export interface MonitorInfo {
  index: number;
  left: number;
  top: number;
  width: number;
  height: number;
  /** DPI scaling factor reported by the OS (e.g. 1.5 for 150%) */
  scale: number;
  isPrimary: boolean;
}

// ─── Frame Metadata ───────────────────────────────────────────────────────────

export interface FrameMetadata {
  /** ISO timestamp when the frame capture started */
  timestamp: string;
  /** Width of the captured image in pixels */
  width: number;
  /** Height of the captured image in pixels */
  height: number;
  /** Milliseconds taken to capture the frame */
  captureDurationMs: number;
  /** Monitor index this frame came from */
  monitorIndex: number;
}

// ─── Python → Electron Messages ───────────────────────────────────────────────

/** Backend is alive and reports its version */
export interface MsgReady {
  type: 'ready';
  version: string;
  pythonVersion: string;
}

/** Backend sends monitor list on startup or when requested */
export interface MsgMonitorList {
  type: 'monitor_list';
  monitors: MonitorInfo[];
}

/** Periodic frame capture status update */
export interface MsgFrameStatus {
  type: 'frame_status';
  frame: FrameMetadata;
  /** Running average fps over the last second (optional) */
  avgFps?: number;
}

/** A preview frame encoded as a base64 JPEG string */
export interface MsgFramePreview {
  type: 'frame_preview';
  /** Base64-encoded JPEG */
  jpegBase64: string;
  frame: FrameMetadata;
}

/** State machine transition */
export interface MsgStateChange {
  type: 'state_change';
  state: AppState;
  reason: string;
}

/** Non-fatal error or warning */
export interface MsgError {
  type: 'error';
  code: string;
  message: string;
  commandId?: string;
  /** Optional extra context */
  detail?: string;
}

/** Backend acknowledged a command */
export interface MsgAck {
  type: 'ack';
  commandId: string;
}

export interface MsgScreenColorSampled {
  type: 'screen_color_sampled';
  commandId: string;
  color?: string;
  error?: string;
}

/** Diagnostic snapshot saved to disk */
export interface MsgSnapshotSaved {
  type: 'snapshot_saved';
  path: string;
}

export interface BoardCandidate {
  id: number;
  rect: { left: number; top: number; width: number; height: number };
  score: number;
  squareWidth: number;
  squareHeight: number;
  corners: [number, number][];
  aspectRatio: number;
  gridScore: number;
  reasons: string[];
}

export interface SquareGridInfo {
  name: string;
  col: number;
  row: number;
  boardCenter: { x: number; y: number };
  imageCenter: { x: number; y: number };
  screenCenter: { x: number; y: number };
  bounds: { x: number; y: number; width: number; height: number };
}

/** Python sends detected board candidates (Phase 2) */
export interface MsgBoardCandidates {
  type: 'board_candidates';
  candidates: BoardCandidate[];
}

/** Python confirms board locked and sends full 64-square grid mapping (Phase 2) */
export interface MsgBoardLocked {
  type: 'board_locked';
  rect: { left: number; top: number; width: number; height: number; screenLeft: number; screenTop: number };
  orientation: 'white_bottom' | 'black_bottom';
  squareWidth: number;
  squareHeight: number;
  squares: SquareGridInfo[];
  tabPlacement?: 'top' | 'bottom';
}

/** Python confirms board unlocked */
export interface MsgBoardUnlocked {
  type: 'board_unlocked';
}

/** Individual square occupancy details (Phase 3) */
export interface SquareOccupancyInfo {
  name: string;
  status: 'EMPTY' | 'OCCUPIED' | 'UNKNOWN';
  color: 'WHITE' | 'BLACK' | 'UNKNOWN';
  confidence: number;
  diffScore: number;
  isStable: boolean;
  appearance?: number[];
}

/** Periodic or on-demand 64-square occupancy update (Phase 3) */
export interface MsgSquareOccupancy {
  type: 'square_occupancy';
  timestamp: string;
  summary: {
    total: number;
    occupied: number;
    empty: number;
    stable: number;
    changing: number;
    isCalibrated: boolean;
  };
  squares: Record<string, SquareOccupancyInfo>;
}

/** Stable visual transition inferred by the Phase 4 classifier. */
export interface MsgMoveDecision {
  type: 'move_decision';
  sourceSquare: string;
  destinationSquare: string;
  capturedSquare: string | null;
  isCapture: boolean;
  kind: 'MOVE' | 'CASTLING' | 'EN_PASSANT' | 'PROMOTION';
  confidence: number;
  decisionReason: string;
  source: 'visual_only';
  movingTeam: 'WHITE' | 'BLACK' | 'UNKNOWN';
}

/** One debounced cosmetic-effect trigger per confidently verified capture. */
export interface MsgCaptureEvent {
  type: 'capture_event';
  eventId: string;
  timestamp: string;
  sourceSquare: string;
  destinationSquare: string;
  capturedSquare: string;
  confidence: number;
  decisionReason: string;
}

/** Screen-overlay data based on the trusted game state, not raw piece-color guesses. */
export interface MsgBoardDebug {
  type: 'board_debug';
  squares: Record<string, 'WHITE' | 'BLACK'>;
  pieceCounts: { WHITE: number; BLACK: number };
  localTeam: 'WHITE' | 'BLACK';
  thinking: string;
  finalAction: string;
  /** Present after R reset: overlay may assign normal opening piece types. */
  pieceTypeSetup?: 'standard';
}

export type PythonMessage =
  | MsgReady
  | MsgMonitorList
  | MsgFrameStatus
  | MsgFramePreview
  | MsgStateChange
  | MsgError
  | MsgAck
  | MsgScreenColorSampled
  | MsgSnapshotSaved
  | MsgBoardCandidates
  | MsgBoardLocked
  | MsgBoardUnlocked
  | MsgSquareOccupancy
  | MsgMoveDecision
  | MsgCaptureEvent
  | MsgBoardDebug;

// ─── Electron → Python Commands ───────────────────────────────────────────────

/** Unique command IDs for ack tracking */
let _cmdCounter = 0;
export function nextCommandId(): string {
  return `cmd-${++_cmdCounter}`;
}

export interface CmdStartCapture {
  type: 'start_capture';
  commandId: string;
  monitorIndex: number;
  /** Target frames per second */
  fps: number;
  /** Whether to send frame previews (lower-res JPEG) */
  sendPreviews: boolean;
}

export interface CmdStopCapture {
  type: 'stop_capture';
  commandId: string;
}

export interface CmdSetMonitor {
  type: 'set_monitor';
  commandId: string;
  monitorIndex: number;
}

export interface CmdGetMonitors {
  type: 'get_monitors';
  commandId: string;
}

export interface CmdSetFps {
  type: 'set_fps';
  commandId: string;
  fps: number;
}

export interface CmdSetPreviewEnabled {
  type: 'set_preview_enabled';
  commandId: string;
  enabled: boolean;
}

export interface CmdSaveSnapshot {
  type: 'save_snapshot';
  commandId: string;
  /** Directory to write the snapshot file; defaults to ./snapshots */
  outputDir?: string;
}

export interface CmdSetDebugMode {
  type: 'set_debug_mode';
  commandId: string;
  enabled: boolean;
}

export interface CmdSetLockedBoard {
  type: 'set_locked_board';
  commandId: string;
  left: number;
  top: number;
  width: number;
  height: number;
  orientation?: 'white_bottom' | 'black_bottom';
}

export interface CmdDetectBoard {
  type: 'detect_board';
  commandId: string;
}

export interface CmdSelectCandidate {
  type: 'select_candidate';
  commandId: string;
  candidateId: number;
}

export interface CmdLockBoard {
  type: 'lock_board';
  commandId: string;
}

export interface CmdUnlockBoard {
  type: 'unlock_board';
  commandId: string;
}

export interface CmdSetOrientation {
  type: 'set_orientation';
  commandId: string;
  orientation: 'white_bottom' | 'black_bottom';
}

export interface CmdCalibrateOccupancy {
  type: 'calibrate_occupancy';
  commandId: string;
}

export interface CmdGetOccupancy {
  type: 'get_occupancy';
  commandId: string;
}

export interface CmdSetPixelPalette {
  type: 'set_pixel_palette';
  commandId: string;
  colors: Record<string, [number, number, number] | null>;
}

export interface CmdSampleScreenColor {
  type: 'sample_screen_color';
  commandId: string;
  monitorIndex: number;
  xRatio: number;
  yRatio: number;
}

/** Find and lock the board on screen without forcing starting pieces. */
export interface CmdFindBoard {
  type: 'find_board';
  commandId: string;
}

/** Reset piece positions to standard 16 vs 16 opening position on the locked board. */
export interface CmdResetPieces {
  type: 'reset_pieces';
  commandId: string;
}

/** Mark the locked board as a standard chess starting position. */
export interface CmdInitializeGame {
  type: 'initialize_game';
  commandId: string;
}

/** Find, lock, and initialize the known opening board state. */
export interface CmdResetGame {
  type: 'reset_game';
  commandId: string;
}

export interface CmdShutdown {
  type: 'shutdown';
  commandId: string;
}

export type ElectronCommand =
  | CmdStartCapture
  | CmdStopCapture
  | CmdSetMonitor
  | CmdGetMonitors
  | CmdSetFps
  | CmdSetPreviewEnabled
  | CmdSaveSnapshot
  | CmdSetDebugMode
  | CmdSetLockedBoard
  | CmdDetectBoard
  | CmdSelectCandidate
  | CmdLockBoard
  | CmdUnlockBoard
  | CmdSetOrientation
  | CmdCalibrateOccupancy
  | CmdGetOccupancy
  | CmdSetPixelPalette
  | CmdSampleScreenColor
  | CmdFindBoard
  | CmdResetPieces
  | CmdInitializeGame
  | CmdResetGame
  | CmdShutdown;
