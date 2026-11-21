/**
 * Electron main process entry point.
 *
 * Phase 1 responsibilities:
 *  - Open the control window.
 *  - Spawn the Python backend via PythonBridge.
 *  - Forward IPC between renderer and Python.
 *  - Handle window lifecycle.
 */

import {
  app,
  BrowserWindow,
  ipcMain,
  screen,
  dialog,
  globalShortcut,
  Menu,
} from 'electron';
import { spawnSync } from 'child_process';
import * as path from 'path';
import * as fs from 'fs';
import { pathToFileURL } from 'url';
import { PythonBridge } from './pythonBridge';
import {
  PythonMessage,
  ElectronCommand,
  nextCommandId,
  AppState,
} from '../shared/protocol';

// ─── Paths ────────────────────────────────────────────────────────────────────

const ROOT = path.resolve(__dirname, '..', '..');
const APP_PATH = app.getAppPath();
const PYTHON_ROOT = app.isPackaged ? path.join(process.resourcesPath, 'app.asar.unpacked') : ROOT;
const PYTHON_SCRIPT = path.join(PYTHON_ROOT, 'python', 'backend.py');
const RENDERER_HTML = path.join(APP_PATH, 'src', 'renderer', 'control.html');
const OVERLAY_HTML = path.join(APP_PATH, 'src', 'renderer', 'overlay.html');
const SCREEN_PICKER_HTML = path.join(APP_PATH, 'src', 'renderer', 'screen-picker.html');
const PRELOAD_JS = path.join(APP_PATH, 'dist', 'preload', 'preload.js');
const PORTABLE_EXECUTABLE_DIR = process.env.PORTABLE_EXECUTABLE_DIR || path.dirname(app.getPath('exe'));
const USER_DATA_DIR = path.join(app.isPackaged ? PORTABLE_EXECUTABLE_DIR : ROOT, '.user-data');
const PROJECT_DATA_DIR = path.join(ROOT, 'data');
const SNAPSHOTS_DIR = path.join(USER_DATA_DIR, 'snapshots');
const LEGACY_USER_DATA_DIR = path.join(app.getPath('appData'), 'chess-vision-fx');
const hasSingleInstanceLock = app.requestSingleInstanceLock();
let userDataReady = false;

if (!hasSingleInstanceLock) {
  app.quit();
} else {
  try {
    if (path.resolve(USER_DATA_DIR) === path.resolve(LEGACY_USER_DATA_DIR)) {
      fs.mkdirSync(USER_DATA_DIR, { recursive: true });
    } else if (!fs.existsSync(USER_DATA_DIR)) {
      if (fs.existsSync(LEGACY_USER_DATA_DIR)) {
        fs.cpSync(LEGACY_USER_DATA_DIR, USER_DATA_DIR, {
          recursive: true,
          force: false,
          errorOnExist: true,
        });
        console.info(`[Main] Migrated app data from ${LEGACY_USER_DATA_DIR} to ${USER_DATA_DIR}; original data was left untouched.`);
      } else {
        fs.mkdirSync(USER_DATA_DIR, { recursive: true });
      }
    } else if (fs.existsSync(LEGACY_USER_DATA_DIR) && fs.readdirSync(USER_DATA_DIR).length === 0) {
      for (const entry of fs.readdirSync(LEGACY_USER_DATA_DIR)) {
        fs.cpSync(path.join(LEGACY_USER_DATA_DIR, entry), path.join(USER_DATA_DIR, entry), {
          recursive: true,
          force: false,
          errorOnExist: true,
        });
      }
      console.info(`[Main] Migrated app data into ${USER_DATA_DIR}; original data was left untouched.`);
    } else if (fs.existsSync(LEGACY_USER_DATA_DIR)) {
      console.warn(`[Main] Keeping existing project-local app data. Legacy app data remains at ${LEGACY_USER_DATA_DIR}.`);
    }
    app.setPath('userData', USER_DATA_DIR);
    userDataReady = true;
  } catch (error) {
    console.error(`[Main] Could not prepare project-local app data at ${USER_DATA_DIR}:`, error);
  }
}

// ─── Global state ─────────────────────────────────────────────────────────────

let controlWindow: BrowserWindow | null = null;
let overlayWindow: BrowserWindow | null = null;
let bridge: PythonBridge | null = null;
let pythonBackendReady = false;
let currentState: AppState = 'NO_BOARD';
// Effects are deliberately independent of board/capture state.  Resetting a
// board must not silently enable visual effects.
let effectsActive = false;
let deathEffectsActive = false;
let effectConfig: unknown = null;
let boardOverlayBounds: Electron.Rectangle | null = null;
let previewHideTimer: NodeJS.Timeout | null = null;
let pendingScreenColorPick: {
  window: BrowserWindow;
  resolve: (color: string | null) => void;
  reject: (error: Error) => void;
  commandId?: string;
} | null = null;

function ensureProjectDataDir(): string {
  fs.mkdirSync(PROJECT_DATA_DIR, { recursive: true });
  return PROJECT_DATA_DIR;
}

function readJsonFileIfExists(filePath: string): unknown | null {
  if (!fs.existsSync(filePath)) return null;
  try {
    const raw = fs.readFileSync(filePath, 'utf8');
    return JSON.parse(raw);
  } catch (error) {
    console.warn(`[Main] Could not parse stored project data at ${filePath}:`, error);
    return null;
  }
}

function writeJsonFile(filePath: string, value: unknown): void {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
}

function gitCommand(args: string[], cwd: string): { ok: boolean; stdout: string; stderr: string; status: number | null } {
  const result = spawnSync('git', args, { cwd, encoding: 'utf8' });
  return {
    ok: result.status === 0,
    stdout: result.stdout || '',
    stderr: result.stderr || '',
    status: result.status,
  };
}

if (hasSingleInstanceLock) {
  app.on('second-instance', () => {
    if (!controlWindow || controlWindow.isDestroyed()) return;
    if (controlWindow.isMinimized()) controlWindow.restore();
    controlWindow.show();
    controlWindow.focus();
  });
}

// ─── Control Window ───────────────────────────────────────────────────────────

function createControlWindow(): BrowserWindow {
  const win = new BrowserWindow({
    width: 900,
    height: 700,
    minWidth: 700,
    minHeight: 500,
    title: 'Chess Vision FX – Control',
    backgroundColor: '#0f0f1a',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: PRELOAD_JS,
      sandbox: false,
    },
  });

  win.webContents.on('did-finish-load', () => {
    if (pythonBackendReady) win.webContents.send('python:ready');
  });
  win.loadFile(RENDERER_HTML);
  // Start maximized as a normal, restorable desktop window (not fullscreen).
  win.maximize();

  if (process.argv.includes('--dev')) {
    win.webContents.openDevTools({ mode: 'detach' });
  }

  win.on('closed', () => {
    controlWindow = null;
  });
  // The overlay has no controls of its own; closing the app window closes the
  // companion overlay too so Electron reaches its normal quit path.
  win.on('close', () => {
    if (overlayWindow && !overlayWindow.isDestroyed()) overlayWindow.close();
  });

  return win;
}

function createOverlayWindow(): BrowserWindow {
  const win = new BrowserWindow({
    width: 400,
    height: 400,
    frame: false,
    transparent: true,
    resizable: false,
    focusable: false,
    skipTaskbar: true,
    alwaysOnTop: true,
    hasShadow: false,
    show: false,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: PRELOAD_JS,
      sandbox: false,
      backgroundThrottling: false,
    },
  });
  win.setIgnoreMouseEvents(true, { forward: true });
  // Keep our own labels out of the desktop frames used for occupancy detection.
  win.setContentProtection(true);
  win.setAlwaysOnTop(true, 'screen-saver');
  win.loadFile(OVERLAY_HTML);
  win.on('closed', () => { overlayWindow = null; });
  return win;
}

// ─── Send to renderer (safe – checks if window is alive) ─────────────────────

function sendToRenderers(channel: string, ...args: unknown[]): void {
  if (controlWindow && !controlWindow.isDestroyed()) {
    controlWindow.webContents.send(channel, ...args);
  }
  if (overlayWindow && !overlayWindow.isDestroyed()) {
    overlayWindow.webContents.send(channel, ...args);
  }
}

function setEffectsActive(active: boolean): void {
  effectsActive = active;

  // F, [, and R are convenience controls only while the app is active.  Releasing
  // them in inactive mode lets the focused application receive normal typing.
  globalShortcut.unregister('F');
  globalShortcut.unregister('R');
  globalShortcut.unregister('[');
  if (effectsActive) {
    globalShortcut.register('F', () => {
      if (overlayWindow && !overlayWindow.isDestroyed()) {
        // F is the active-session overlay debug toggle; it has no bearing on FX.
        overlayWindow.webContents.send('toggle-labels');
      }
    });
    globalShortcut.register('[', () => {
      if (bridge?.isRunning()) {
        bridge.send({ type: 'find_board', commandId: nextCommandId() });
      }
    });
    globalShortcut.register('R', () => {
      if (bridge?.isRunning()) {
        bridge.send({ type: 'reset_pieces', commandId: nextCommandId() });
      }
    });
  }

  sendToRenderers('effects-active', effectsActive);

  if (!overlayWindow || overlayWindow.isDestroyed()) return;
  if (effectsActive) {
    // Bounds are updated whenever a board is locked; only make the overlay
    // visible once the user explicitly enables the app.
    overlayWindow.setAlwaysOnTop(true, 'screen-saver');
    overlayWindow.showInactive();
    overlayWindow.moveTop();
  } else {
    overlayWindow.hide();
  }
}

const OVERLAY_TAB_HEIGHT = 46;

function updateOverlayBounds(message: PythonMessage): void {
  if (message.type !== 'board_locked' || !overlayWindow) return;
  const rect = message.rect;
  const point = screen.screenToDipPoint({ x: rect.screenLeft, y: rect.screenTop });
  const display = screen.getDisplayNearestPoint(point);
  const scale = display.scaleFactor || 1;
  const dipW = Math.round(rect.width / scale);
  const dipH = Math.round(rect.height / scale);

  const placeAbove = point.y >= OVERLAY_TAB_HEIGHT + 2;
  const winY = placeAbove ? point.y - OVERLAY_TAB_HEIGHT : point.y;
  const winH = dipH + OVERLAY_TAB_HEIGHT;

  boardOverlayBounds = {
    x: point.x,
    y: winY,
    width: dipW,
    height: winH,
  };
  if (!previewHideTimer) overlayWindow.setBounds(boardOverlayBounds);

  message.tabPlacement = placeAbove ? 'top' : 'bottom';
}

// ─── Python bridge setup ──────────────────────────────────────────────────────

function startPythonBridge(): void {
  bridge = new PythonBridge(PYTHON_SCRIPT);

  bridge.on('ready', () => {
    pythonBackendReady = true;
    console.log('[Main] Python backend ready');
    sendToRenderers('python:ready');
    // Request monitor list on first connect; do NOT auto-start capture
    // (capture starts only when the user presses R to lock the board)
    bridge?.send({ type: 'get_monitors', commandId: nextCommandId() });
    bridge?.resetRestartCount();
  });

  bridge.on('message', (msg: PythonMessage) => {
    if (msg.type === 'screen_color_sampled') {
      const pending = pendingScreenColorPick;
      if (!pending || pending.commandId !== msg.commandId) return;
      pendingScreenColorPick = null;
      if (msg.error || !msg.color || !/^#[0-9a-f]{6}$/i.test(msg.color)) {
        pending.reject(new Error(msg.error || 'The sampled screen color was invalid.'));
      } else {
        pending.resolve(msg.color.toUpperCase());
      }
      if (!pending.window.isDestroyed()) pending.window.close();
      return;
    }

    // Forward every typed message to the renderer
    updateOverlayBounds(msg);
    sendToRenderers('python:message', msg);

    // Keep local state in sync for main-process decisions
    if (msg.type === 'state_change') {
      currentState = msg.state;
    }
  });

  bridge.on('stderr', (line: string) => {
    sendToRenderers('python:stderr', line);
  });

  bridge.on('crash', (code, signal) => {
    pythonBackendReady = false;
    console.error(`[Main] Python crashed code=${code} signal=${signal}`);
    sendToRenderers('python:message', {
      type: 'error',
      code: 'PROCESS_CRASH',
      message: `Python process exited unexpectedly (code=${code})`,
    } as PythonMessage);
  });

  bridge.start();
}

// ─── IPC handlers: renderer → main ───────────────────────────────────────────

function registerIpcHandlers(): void {
  // Renderer sends a command; main forwards it to Python
  ipcMain.on('command', (_event, cmd: ElectronCommand) => {
    if (!bridge?.isRunning()) {
      sendToRenderers('python:message', {
        type: 'error',
        code: 'NOT_RUNNING',
        message: 'Python backend is not running.',
      } as PythonMessage);
      return;
    }
    bridge.send(cmd);
  });

  // Renderer asks for the list of Electron-side display info
  ipcMain.handle('get-displays', () => {
    return screen.getAllDisplays().map((d, i) => ({
      index: i,
      id: d.id,
      label: d.label || `Display ${i + 1}`,
      bounds: d.bounds,
      scaleFactor: d.scaleFactor,
      isPrimary: d.id === screen.getPrimaryDisplay().id,
    }));
  });

  // Open a save-screenshot dialog and relay the path back to Python
  ipcMain.handle('save-snapshot-dialog', async () => {
    if (!controlWindow) return null;
    const result = await dialog.showSaveDialog(controlWindow, {
      title: 'Save Diagnostic Snapshot',
      defaultPath: path.join(SNAPSHOTS_DIR, `snapshot-${Date.now()}.json`),
      filters: [{ name: 'JSON', extensions: ['json'] }],
    });
    if (result.canceled || !result.filePath) return null;
    const dir = path.dirname(result.filePath);
    bridge?.send({
      type: 'save_snapshot',
      commandId: nextCommandId(),
      outputDir: dir,
    });
    return result.filePath;
  });

  ipcMain.handle('load-project-settings', () => {
    const dir = ensureProjectDataDir();
    const squareThemesPath = path.join(dir, 'board-themes.json');
    const effectConfigPath = path.join(dir, 'effects.json');
    return {
      squareThemes: readJsonFileIfExists(squareThemesPath),
      fxConfig: readJsonFileIfExists(effectConfigPath),
    };
  });

  ipcMain.handle('save-project-settings', (_event, settings: { squareThemes?: unknown; fxConfig?: unknown }) => {
    const dir = ensureProjectDataDir();
    const messages: string[] = [];
    if (settings.squareThemes !== undefined) {
      const squareThemesPath = path.join(dir, 'board-themes.json');
      writeJsonFile(squareThemesPath, settings.squareThemes);
      messages.push(`Saved square themes to ${squareThemesPath}`);
    }
    if (settings.fxConfig !== undefined) {
      const effectConfigPath = path.join(dir, 'effects.json');
      writeJsonFile(effectConfigPath, settings.fxConfig);
      messages.push(`Saved effect config to ${effectConfigPath}`);
    }
    return { ok: true, message: messages.join('; ') || 'No project settings were saved.' };
  });

  ipcMain.handle('sync-project-data-to-github', () => {
    const dir = ensureProjectDataDir();
    const repoStatus = gitCommand(['status', '--short', '--', 'data'], ROOT);
    if (!repoStatus.ok) {
      return {
        ok: false,
        changed: false,
        message: `Git is unavailable or the repo is not initialized: ${repoStatus.stderr || repoStatus.stdout || 'unknown error'}`,
      };
    }

    const fileSet = ['data/board-themes.json', 'data/effects.json'];
    const addResult = gitCommand(['add', ...fileSet], ROOT);
    if (!addResult.ok) {
      return { ok: false, changed: false, message: `Git add failed: ${addResult.stderr || addResult.stdout || 'unknown error'}` };
    }

    const statusAfterAdd = gitCommand(['status', '--short', '--', 'data'], ROOT);
    const hasChanges = Boolean((statusAfterAdd.stdout || '').trim());
    if (!hasChanges) {
      return { ok: true, changed: false, message: 'No saved project settings changed since the last Git sync.' };
    }

    const commitResult = gitCommand(['commit', '-m', 'Update Chess Vision FX saved settings'], ROOT);
    if (!commitResult.ok) {
      const combined = `${commitResult.stdout || ''}\n${commitResult.stderr || ''}`.trim();
      if (combined.includes('nothing to commit') || combined.includes('no changes added')) {
        return { ok: true, changed: false, message: 'No saved project settings changed since the last Git sync.' };
      }
      return { ok: false, changed: true, message: `Git commit failed: ${combined || 'unknown error'}` };
    }

    const pushResult = gitCommand(['push', 'origin', 'HEAD'], ROOT);
    if (!pushResult.ok) {
      const combined = `${pushResult.stdout || ''}\n${pushResult.stderr || ''}`.trim();
      return { ok: false, changed: true, message: `Git push failed: ${combined || 'unknown error'}` };
    }

    return {
      ok: true,
      changed: true,
      message: 'Saved settings were committed and pushed to GitHub.',
    };
  });

  // Renderer can query current app state
  ipcMain.handle('get-app-state', () => currentState);

  ipcMain.handle('get-effects-active', () => effectsActive);
  ipcMain.handle('set-effects-active', (_event, active: boolean) => {
    setEffectsActive(Boolean(active));
    return effectsActive;
  });
  ipcMain.handle('get-death-effects-active', () => deathEffectsActive);
  ipcMain.handle('set-death-effects-active', (_event, active: boolean) => {
    deathEffectsActive = Boolean(active);
    sendToRenderers('death-effects-active', deathEffectsActive);
    return deathEffectsActive;
  });
  ipcMain.handle('get-effect-config', () => effectConfig);
  ipcMain.handle('set-effect-config', (_event, config: unknown) => {
    effectConfig = config;
    sendToRenderers('effect-config', effectConfig);
    return effectConfig;
  });
  ipcMain.handle('test-effect', (_event, square: string) => {
    if (overlayWindow && !overlayWindow.isDestroyed()) overlayWindow.webContents.send('test-effect', square);
  });
  ipcMain.handle('test-effect-preview', async (_event, previewRect: { left: number; top: number; width: number; height: number }) => {
    if (!controlWindow || !overlayWindow || overlayWindow.isDestroyed()) return;
    const content = controlWindow.getContentBounds();
    const target = { x: Math.round(content.x + previewRect.left + previewRect.width / 2), y: Math.round(content.y + previewRect.top + previewRect.height / 2) };
    const display = screen.getDisplayNearestPoint(target);
    // The small black square is an anchor, not a clipping mask. The overlay
    // spans its display so particles can follow their normal trajectory.
    overlayWindow.setBounds(display.bounds);
    overlayWindow.setAlwaysOnTop(true, 'screen-saver');
    overlayWindow.showInactive();
    overlayWindow.moveTop();
    // Let Chromium apply the new bounds before the emitter reads its canvas
    // dimensions. This also makes preview emission reliable after window moves.
    await new Promise<void>(resolve => setTimeout(resolve, 50));
    if (overlayWindow.isDestroyed()) return;
    overlayWindow.webContents.send('test-effect', {
      kind: 'preview',
      x: (target.x - display.bounds.x) / display.bounds.width,
      y: (target.y - display.bounds.y) / display.bounds.height,
    });
    if (previewHideTimer) clearTimeout(previewHideTimer);
    previewHideTimer = setTimeout(() => {
      previewHideTimer = null;
      if (!overlayWindow || overlayWindow.isDestroyed()) return;
      if (boardOverlayBounds) overlayWindow.setBounds(boardOverlayBounds);
      if (!effectsActive) overlayWindow.hide();
    }, 3000);
  });
  ipcMain.handle('select-effect-image', async () => {
    if (!controlWindow) return null;
    const result = await dialog.showOpenDialog(controlWindow, {
      title: 'Choose particle image', properties: ['openFile'],
      filters: [{ name: 'Images', extensions: ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp'] }, { name: 'All files', extensions: ['*'] }],
    });
    return result.canceled || !result.filePaths[0] ? null : pathToFileURL(result.filePaths[0]).href;
  });

  ipcMain.handle('pick-screen-color', async () => {
    if (pendingScreenColorPick) throw new Error('A screen color picker is already open.');

    const controlWasVisible = Boolean(controlWindow && controlWindow.isVisible());
    const overlayWasVisible = Boolean(overlayWindow && overlayWindow.isVisible());
    if (controlWasVisible) controlWindow?.hide();
    if (overlayWasVisible) overlayWindow?.hide();

    try {
      const displays = screen.getAllDisplays();
      if (displays.length === 0) throw new Error('No displays are available for screen color picking.');
      const virtualBounds = {
        left: Math.min(...displays.map(display => display.bounds.x)),
        top: Math.min(...displays.map(display => display.bounds.y)),
        right: Math.max(...displays.map(display => display.bounds.x + display.bounds.width)),
        bottom: Math.max(...displays.map(display => display.bounds.y + display.bounds.height)),
      };
      const picker = new BrowserWindow({
        x: virtualBounds.left,
        y: virtualBounds.top,
        width: virtualBounds.right - virtualBounds.left,
        height: virtualBounds.bottom - virtualBounds.top,
        frame: false,
        transparent: true,
        resizable: false,
        movable: false,
        focusable: true,
        skipTaskbar: true,
        alwaysOnTop: true,
        hasShadow: false,
        show: false,
        webPreferences: {
          nodeIntegration: false,
          contextIsolation: true,
          preload: PRELOAD_JS,
          sandbox: false,
        },
      });
      picker.setAlwaysOnTop(true, 'screen-saver');
      picker.setContentProtection(true);

      return await new Promise<string | null>((resolve, reject) => {
        pendingScreenColorPick = { window: picker, resolve, reject };
        picker.once('closed', () => {
          if (pendingScreenColorPick?.window !== picker) return;
          pendingScreenColorPick = null;
          resolve(null);
        });
        picker.webContents.once('did-finish-load', () => {
          if (picker.isDestroyed()) return;
          picker.show();
          picker.focus();
          picker.webContents.send('screen-color-pick-ready');
        });
        picker.webContents.once('did-fail-load', (_event, errorCode, errorDescription) => {
          if (pendingScreenColorPick?.window !== picker) return;
          pendingScreenColorPick = null;
          reject(new Error(`Could not open screen color picker (${errorCode}): ${errorDescription}`));
          if (!picker.isDestroyed()) picker.destroy();
        });
        void picker.loadFile(SCREEN_PICKER_HTML).catch(error => {
          if (pendingScreenColorPick?.window !== picker) return;
          pendingScreenColorPick = null;
          reject(error instanceof Error ? error : new Error(String(error)));
          if (!picker.isDestroyed()) picker.destroy();
        });
      });
    } finally {
      if (controlWasVisible && controlWindow && !controlWindow.isDestroyed()) {
        controlWindow.show();
        controlWindow.focus();
      }
      if (overlayWasVisible && (effectsActive || previewHideTimer) && overlayWindow && !overlayWindow.isDestroyed()) {
        overlayWindow.showInactive();
        overlayWindow.moveTop();
      }
    }
  });

  ipcMain.on('screen-color-picked', (event, point: unknown) => {
    const pending = pendingScreenColorPick;
    if (!pending || event.sender !== pending.window.webContents) return;
    if (
      !point || typeof point !== 'object' ||
      !Number.isFinite((point as { x?: unknown }).x) ||
      !Number.isFinite((point as { y?: unknown }).y)
    ) {
      console.error('[Main] Screen color picker returned an invalid screen point.');
      return;
    }
    const { x, y } = point as { x: number; y: number };
    const bounds = pending.window.getBounds();
    const target = { x: x + bounds.x, y: y + bounds.y };
    pending.window.hide();
    const displays = screen.getAllDisplays();
    const display = screen.getDisplayNearestPoint(target);
    const monitorIndex = displays.findIndex(candidate => candidate.id === display.id);
    if (monitorIndex < 0 || !bridge?.isRunning()) {
      pendingScreenColorPick = null;
      pending.reject(new Error('The selected display or screen capture service is unavailable.'));
      if (!pending.window.isDestroyed()) pending.window.close();
      return;
    }
    const commandId = nextCommandId();
    pending.commandId = commandId;
    if (!bridge.send({
      type: 'sample_screen_color',
      commandId,
      monitorIndex,
      xRatio: (target.x - display.bounds.x) / display.bounds.width,
      yRatio: (target.y - display.bounds.y) / display.bounds.height,
    })) {
      pendingScreenColorPick = null;
      pending.reject(new Error('Could not send the screen color sample request to the capture service.'));
      if (!pending.window.isDestroyed()) pending.window.close();
    }
  });

  ipcMain.on('screen-color-pick-cancelled', event => {
    const pending = pendingScreenColorPick;
    if (!pending || event.sender !== pending.window.webContents) return;
    pendingScreenColorPick = null;
    pending.resolve(null);
    if (!pending.window.isDestroyed()) pending.window.close();
  });
}

// ─── App lifecycle ────────────────────────────────────────────────────────────

app.whenReady().then(() => {
  if (!hasSingleInstanceLock) return;
  if (!userDataReady || !fs.existsSync(USER_DATA_DIR)) {
    console.error(`[Main] Project-local app data was not initialized successfully at ${USER_DATA_DIR}.`);
    app.quit();
    return;
  }
  // The native File/Edit/View/Help menu is not part of this focused control UI.
  Menu.setApplicationMenu(null);
  // Ensure snapshots directory exists
  if (!fs.existsSync(SNAPSHOTS_DIR)) {
    fs.mkdirSync(SNAPSHOTS_DIR, { recursive: true });
  }

  registerIpcHandlers();
  controlWindow = createControlWindow();
  overlayWindow = createOverlayWindow();
  globalShortcut.register(']', () => {
    setEffectsActive(!effectsActive);
  });
  startPythonBridge();

  app.on('activate', () => {
    if (!controlWindow) {
      controlWindow = createControlWindow();
    }
  });
});

app.on('window-all-closed', async () => {
  console.log('[Main] All windows closed, shutting down');
  if (bridge) {
    await bridge.shutdown();
  }
  app.quit();
});

app.on('will-quit', () => globalShortcut.unregisterAll());

app.on('before-quit', async () => {
  if (bridge?.isRunning()) {
    await bridge.shutdown();
  }
});
