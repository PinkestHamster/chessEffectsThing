/**
 * PythonBridge – manages the Python child process lifetime.
 *
 * Responsibilities:
 *  - Spawn / kill / restart the process.
 *  - Route line-delimited JSON from stdout → typed messages.
 *  - Forward stderr to the application logger.
 *  - Send typed command objects to stdin.
 *  - Emit events so the rest of main can react.
 */

import { EventEmitter } from 'events';
import { ChildProcess, spawn } from 'child_process';
import * as readline from 'readline';
import * as path from 'path';
import { PythonMessage, ElectronCommand } from '../shared/protocol';

export interface BridgeEvents {
  message: (msg: PythonMessage) => void;
  stderr: (line: string) => void;
  crash: (code: number | null, signal: string | null) => void;
  ready: () => void;
}

export class PythonBridge extends EventEmitter {
  // Typed overloads for on/emit so callers get type safety
  on<K extends keyof BridgeEvents>(event: K, listener: BridgeEvents[K]): this;
  on(event: string, listener: (...args: unknown[]) => void): this;
  on(event: string, listener: (...args: unknown[]) => void): this {
    return super.on(event, listener);
  }

  emit<K extends keyof BridgeEvents>(event: K, ...args: Parameters<BridgeEvents[K]>): boolean;
  emit(event: string, ...args: unknown[]): boolean;
  emit(event: string, ...args: unknown[]): boolean {
    return super.emit(event, ...args);
  }
  private proc: ChildProcess | null = null;
  private restarting = false;
  private shutdownRequested = false;
  private readonly scriptPath: string;
  private readonly pythonExe: string;
  private restartCount = 0;
  private readonly maxRestarts = 5;

  constructor(scriptPath: string, pythonExe = 'python') {
    super();
    this.scriptPath = scriptPath;
    this.pythonExe = pythonExe;
  }

  /** Start the Python backend process */
  start(): void {
    if (this.proc) {
      console.warn('[Bridge] start() called but process already running');
      return;
    }
    this.shutdownRequested = false;
    this._spawn();
  }

  private _spawn(): void {
    const proc = spawn(this.pythonExe, [this.scriptPath], {
      stdio: ['pipe', 'pipe', 'pipe'],
      // Ensure subprocess inherits a sane environment
      env: { ...process.env },
    });

    this.proc = proc;
    console.log(`[Bridge] Spawned Python PID ${proc.pid} from ${this.scriptPath}`);

    // ── stdout: line-delimited JSON protocol messages ────────────────────────
    const rl = readline.createInterface({ input: proc.stdout! });
    rl.on('line', (line) => {
      const trimmed = line.trim();
      if (!trimmed) return;
      try {
        const msg = JSON.parse(trimmed) as PythonMessage;
        if (!msg.type) {
          console.error('[Bridge] Received message without type field:', trimmed);
          return;
        }
        this.emit('message', msg);
        if (msg.type === 'ready') this.emit('ready');
      } catch (err) {
        console.error('[Bridge] Failed to parse stdout line:', trimmed, err);
      }
    });

    // ── stderr: diagnostics from Python ─────────────────────────────────────
    const errRl = readline.createInterface({ input: proc.stderr! });
    errRl.on('line', (line) => {
      this.emit('stderr', line);
      // Mirror Python stderr into Node console for dev convenience
      console.log(`[Python] ${line}`);
    });

    // ── process exit ─────────────────────────────────────────────────────────
    proc.on('close', (code, signal) => {
      console.log(`[Bridge] Python process closed code=${code} signal=${signal}`);
      this.proc = null;

      if (!this.shutdownRequested) {
        this.emit('crash', code, signal);
        this._scheduleRestart();
      }
    });

    proc.on('error', (err) => {
      console.error('[Bridge] Failed to spawn Python:', err.message);
      this.proc = null;
      this.emit('crash', null, null);
      this._scheduleRestart();
    });
  }

  private _scheduleRestart(): void {
    if (this.shutdownRequested) return;
    if (this.restarting) return;

    if (this.restartCount >= this.maxRestarts) {
      console.error('[Bridge] Max restart attempts reached. Giving up.');
      return;
    }

    this.restarting = true;
    this.restartCount++;
    const delay = Math.min(1000 * this.restartCount, 8000);
    console.log(`[Bridge] Restarting Python in ${delay}ms (attempt ${this.restartCount})`);

    setTimeout(() => {
      this.restarting = false;
      if (!this.shutdownRequested) {
        this._spawn();
      }
    }, delay);
  }

  /** Send a typed command to Python via stdin */
  send(cmd: ElectronCommand): boolean {
    if (!this.proc || !this.proc.stdin?.writable) {
      console.warn('[Bridge] Cannot send command – process not running:', cmd.type);
      return false;
    }
    try {
      const json = JSON.stringify(cmd) + '\n';
      this.proc.stdin.write(json);
      return true;
    } catch (err) {
      console.error('[Bridge] Failed to write to Python stdin:', err);
      return false;
    }
  }

  /** Gracefully shut down the Python process */
  async shutdown(timeoutMs = 3000): Promise<void> {
    this.shutdownRequested = true;
    if (!this.proc) return;

    this.send({ type: 'shutdown', commandId: 'shutdown-0' });

    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        console.warn('[Bridge] Shutdown timed out – killing process');
        this.proc?.kill('SIGKILL');
        resolve();
      }, timeoutMs);

      this.proc!.once('close', () => {
        clearTimeout(timer);
        resolve();
      });
    });
  }

  isRunning(): boolean {
    return this.proc !== null && !this.proc.killed;
  }

  resetRestartCount(): void {
    this.restartCount = 0;
  }
}
