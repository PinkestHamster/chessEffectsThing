/**
 * Preload script – runs in the renderer context with Node access.
 *
 * Exposes a narrow, explicitly typed API to the renderer via contextBridge.
 * The renderer has NO direct access to Node or Electron internals.
 */

import { contextBridge, ipcRenderer } from 'electron';
import type { ElectronCommand, PythonMessage, AppState } from '../shared/protocol';

// Type for display info returned by get-displays
export interface DisplayInfo {
  index: number;
  id: number;
  label: string;
  bounds: { x: number; y: number; width: number; height: number };
  scaleFactor: number;
  isPrimary: boolean;
}

const api = {
  /** Send a typed command to the Python backend (fire-and-forget) */
  sendCommand(cmd: ElectronCommand): void {
    ipcRenderer.send('command', cmd);
  },

  /** Get the list of connected displays as seen by Electron */
  getDisplays(): Promise<DisplayInfo[]> {
    return ipcRenderer.invoke('get-displays');
  },

  /** Get the current application state */
  getAppState(): Promise<AppState> {
    return ipcRenderer.invoke('get-app-state');
  },

  /** Whether capture effects are enabled by the user. */
  getEffectsActive(): Promise<boolean> {
    return ipcRenderer.invoke('get-effects-active');
  },

  /** Enable or disable capture effects without changing board calibration. */
  setEffectsActive(active: boolean): Promise<boolean> {
    return ipcRenderer.invoke('set-effects-active', active);
  },

  /** Whether team defeat effects are enabled. */
  getDeathEffectsActive(): Promise<boolean> {
    return ipcRenderer.invoke('get-death-effects-active');
  },

  /** Enable or disable team defeat effects independently of other effects. */
  setDeathEffectsActive(active: boolean): Promise<boolean> {
    return ipcRenderer.invoke('set-death-effects-active', active);
  },

  /** Current editable particle effect definition. */
  getEffectConfig(): Promise<unknown> {
    return ipcRenderer.invoke('get-effect-config');
  },

  /** Update the live particle effect definition in both renderer windows. */
  setEffectConfig(config: unknown): Promise<unknown> {
    return ipcRenderer.invoke('set-effect-config', config);
  },
  testEffect(square = 'e4'): Promise<void> {
    return ipcRenderer.invoke('test-effect', square);
  },
  testEffectPreview(previewRect: { left: number; top: number; width: number; height: number }): Promise<void> {
    return ipcRenderer.invoke('test-effect-preview', previewRect);
  },
  selectEffectImage(): Promise<string | null> {
    return ipcRenderer.invoke('select-effect-image');
  },
  pickScreenColor(): Promise<string | null> {
    return ipcRenderer.invoke('pick-screen-color');
  },
  onScreenColorPickReady(cb: () => void): () => void {
    const handler = () => cb();
    ipcRenderer.on('screen-color-pick-ready', handler);
    return () => ipcRenderer.removeListener('screen-color-pick-ready', handler);
  },
  completeScreenColorPickAt(x: number, y: number): void {
    ipcRenderer.send('screen-color-picked', { x, y });
  },
  cancelScreenColorPick(): void {
    ipcRenderer.send('screen-color-pick-cancelled');
  },

  /** Open a dialog to choose a snapshot save location */
  saveSnapshotDialog(): Promise<string | null> {
    return ipcRenderer.invoke('save-snapshot-dialog');
  },

  /** Load the repo-backed project settings that should be committed to GitHub. */
  loadProjectSettings(): Promise<{ squareThemes?: unknown; fxConfig?: unknown }> {
    return ipcRenderer.invoke('load-project-settings');
  },

  /** Save the repo-backed project settings as separate JSON files. */
  saveProjectSettings(settings: { squareThemes?: unknown; fxConfig?: unknown }): Promise<{ ok: boolean; message: string }> {
    return ipcRenderer.invoke('save-project-settings', settings);
  },

  /** Commit and push the repo-backed project settings to GitHub. */
  syncProjectDataToGitHub(): Promise<{ ok: boolean; message: string; changed: boolean }> {
    return ipcRenderer.invoke('sync-project-data-to-github');
  },

  // ── Event subscriptions ────────────────────────────────────────────────────

  /** Called when the Python backend sends any protocol message */
  onPythonMessage(cb: (msg: PythonMessage) => void): () => void {
    const handler = (_: unknown, msg: PythonMessage) => cb(msg);
    ipcRenderer.on('python:message', handler);
    return () => ipcRenderer.removeListener('python:message', handler);
  },

  /** Called when the Python backend is ready */
  onPythonReady(cb: () => void): () => void {
    ipcRenderer.on('python:ready', cb);
    return () => ipcRenderer.removeListener('python:ready', cb);
  },

  /** Called for every line written to Python's stderr */
  onPythonStderr(cb: (line: string) => void): () => void {
    const handler = (_: unknown, line: string) => cb(line);
    ipcRenderer.on('python:stderr', handler);
    return () => ipcRenderer.removeListener('python:stderr', handler);
  },
  /** Subscribe to arbitrary IPC channels from the main process (e.g. toggle-labels) */
  onMainMessage(channel: string, cb: (...args: unknown[]) => void): () => void {
    const allowed = ['toggle-labels', 'effects-active', 'death-effects-active', 'effect-config', 'test-effect'];
    if (!allowed.includes(channel)) return () => {};
    const handler = (_: unknown, ...args: unknown[]) => cb(...args);
    ipcRenderer.on(channel, handler);
    return () => ipcRenderer.removeListener(channel, handler);
  },
};

contextBridge.exposeInMainWorld('cvfx', api);

// Extend the global Window type so TypeScript knows about window.cvfx
declare global {
  interface Window {
    cvfx: typeof api;
  }
}
