/**
 * Chess Vision FX – Control Window Renderer Script
 *
 * Runs in the browser context. Uses only window.cvfx (the preload API).
 * No direct Node/Electron access.
 */

// ─── Type helpers ─────────────────────────────────────────────────────────────
// We can use JSDoc types since this is plain JS loaded directly in HTML.
// PythonMessage and DisplayInfo shapes are mirrored here for IDE hints.

// ─── Constants ────────────────────────────────────────────────────────────────
const MAX_LOG_ENTRIES = 200;

// ─── State ────────────────────────────────────────────────────────────────────
let captureRunning = false;
let effectsActive = false;
let pythonBackendReady = false;
let lastAppliedSquarePalette = '';
let pendingSquarePaletteCommandId = '';
let currentMonitorIndex = 0;
let logCount = 0;

// ─── DOM refs ─────────────────────────────────────────────────────────────────
const elStateBadge      = /** @type {HTMLElement} */ (document.getElementById('state-badge'));
const elStateLabel      = /** @type {HTMLElement} */ (document.getElementById('state-label'));
const elPythonStatus    = /** @type {HTMLElement} */ (document.getElementById('python-status'));
const elPythonLabel     = /** @type {HTMLElement} */ (document.getElementById('python-status-label'));
const elMonitorSelect   = /** @type {HTMLSelectElement} */ (document.getElementById('monitor-select'));
const elFpsInput        = /** @type {HTMLInputElement}  */ (document.getElementById('fps-input'));
const elDebugToggle     = /** @type {HTMLInputElement}  */ (document.getElementById('debug-toggle'));
const elDeathEffectsToggle = /** @type {HTMLInputElement} */ (document.getElementById('death-effects-toggle'));
const elBtnStart        = /** @type {HTMLButtonElement} */ (document.getElementById('btn-start'));
const elBtnStop         = /** @type {HTMLButtonElement} */ (document.getElementById('btn-stop'));
const elBtnRefresh      = /** @type {HTMLButtonElement} */ (document.getElementById('btn-refresh-monitors'));
const elBtnClearLog     = /** @type {HTMLButtonElement} */ (document.getElementById('btn-clear-log'));
const elLogList         = /** @type {HTMLElement}       */ (document.getElementById('log-list'));
const elPreviewCanvas   = /** @type {HTMLCanvasElement} */ (document.getElementById('preview-canvas'));
const elPreviewPh       = /** @type {HTMLElement}       */ (document.getElementById('preview-placeholder'));
const elPreviewStats    = /** @type {HTMLElement}       */ (document.getElementById('preview-stats'));
const elLastError       = /** @type {HTMLElement}       */ (document.getElementById('last-error'));
const elLastErrorText   = /** @type {HTMLElement}       */ (document.getElementById('last-error-text'));

// Phase 2 Board DOM elements
const elBtnAutoDetect        = /** @type {HTMLButtonElement} */ (document.getElementById('btn-auto-detect'));
const elBtnManualCal         = /** @type {HTMLButtonElement} */ (document.getElementById('btn-manual-cal'));
const elBtnApplyManualCal    = /** @type {HTMLButtonElement} */ (document.getElementById('btn-apply-manual-cal'));
const elBtnLockBoard         = /** @type {HTMLButtonElement} */ (document.getElementById('btn-lock-board'));
const elBtnToggleOrientation = /** @type {HTMLButtonElement} */ (document.getElementById('btn-toggle-orientation'));
const elBtnStartPosition     = /** @type {HTMLButtonElement} */ (document.getElementById('btn-start-position'));
const elCandidateGroup       = /** @type {HTMLElement}       */ (document.getElementById('candidate-group'));
const elCandidateSelect      = /** @type {HTMLSelectElement} */ (document.getElementById('candidate-select'));
const elManualCalInputs      = /** @type {HTMLElement}       */ (document.getElementById('manual-cal-inputs'));
const elBoardSummary         = /** @type {HTMLElement}       */ (document.getElementById('board-summary'));
const elBoardStatusBadge     = /** @type {HTMLElement}       */ (document.getElementById('board-status-badge'));
const elCalX                 = /** @type {HTMLInputElement}  */ (document.getElementById('cal-x'));
const elCalY                 = /** @type {HTMLInputElement}  */ (document.getElementById('cal-y'));
const elCalW                 = /** @type {HTMLInputElement}  */ (document.getElementById('cal-w'));
const elCalH                 = /** @type {HTMLInputElement}  */ (document.getElementById('cal-h'));
const elDbgOccupancy         = /** @type {HTMLElement}       */ (document.getElementById('dbg-occupancy-summary'));
const elDbgChanges           = /** @type {HTMLElement}       */ (document.getElementById('dbg-board-changes'));
const elDbgCaptureEvent      = /** @type {HTMLElement}       */ (document.getElementById('dbg-capture-event'));
const elDbgMoveScan          = /** @type {HTMLElement}       */ (document.getElementById('dbg-move-scan'));
const elOccupancyGrid        = /** @type {HTMLElement}       */ (document.getElementById('occupancy-grid'));

// ─── Particle FX editor ──────────────────────────────────────────────────────
const EMISSION_DEFAULT = {
  count: 5, zIndex: 0, position: { x: 0, y: 0 }, speed: [70, 190], rotation: [0, 360], direction: [-180, 180], directional: false,
  acceleration: 0, drag: 0, rotationSpeed: [-180, 180], lifetime: [.45, .9], shape: 'star', imageId: '', flipbook: { size: 2 },
  glow: 0, imageColorMode: 'tint',
  size: [{t:0,v:[50,50]},{t:1,v:[50,50]}], transparency: [{t:0,v:0},{t:.72,v:.15},{t:1,v:1}],
  color: [{t:0,v:[255,244,176]},{t:.5,v:[255,140,66]},{t:1,v:[217,70,239]}]
};
const FX_DEFAULT = { selectedFunction: 'default-capture.fx.json', functions: {
  'default-capture.fx.json': { emissions: [JSON.parse(JSON.stringify(EMISSION_DEFAULT))] }
}, movementDuration: 0.5 };
const FX_CONFIG_KEY = 'chess-fx-config';
const FX_CONFIG_BACKUP_KEY = 'chess-fx-config-backup';
const SQUARE_THEMES_KEY = 'chess-square-color-themes';
const SQUARE_COLOR_KEYS = [
  'move_highlight_light', 'move_highlight_dark',
  'normal_light', 'normal_dark',
  'checked_king_light', 'checked_king_dark',
  'capturable_target_light', 'capturable_target_dark',
  'capturable_target_highlight_light', 'capturable_target_highlight_dark',
];
const OPTIONAL_SQUARE_COLOR_KEYS = new Set([
  'capturable_target_highlight_light', 'capturable_target_highlight_dark',
]);
const SQUARE_COLOR_LABELS = {
  move_highlight_light: 'Move highlight · light',
  move_highlight_dark: 'Move highlight · dark',
  normal_light: 'Normal background · light',
  normal_dark: 'Normal background · dark',
  checked_king_light: 'Checked king · light',
  checked_king_dark: 'Checked king · dark',
  capturable_target_light: 'Capturable target · light',
  capturable_target_dark: 'Capturable target · dark',
  capturable_target_highlight_light: 'Capturable target on highlighted square · light',
  capturable_target_highlight_dark: 'Capturable target on highlighted square · dark',
};
const CHESS_COM_PALETTE = {
  move_highlight_light: '#EEAEB6',
  move_highlight_dark: '#EC9BA8',
  normal_light: '#FEFFFE',
  normal_dark: '#FBD9E1',
  checked_king_light: '#F19299',
  checked_king_dark: '#EF818C',
  capturable_target_light: '#DADBDA',
  capturable_target_dark: '#CC959C',
  capturable_target_highlight_light: null,
  capturable_target_highlight_dark: null,
};
let squareThemes = [{ name: 'Chess.com Pink', builtIn: true, colors: { ...CHESS_COM_PALETTE } }];
let selectedSquareTheme = 'Chess.com Pink';
const PIECE_TYPES = ['pawn', 'queen', 'rook', 'bishop', 'king', 'knight'];
let fxConfig = JSON.parse(JSON.stringify(FX_DEFAULT));
let fxConfigReady = false;
let fxConfigSaveBlockedLogged = false;
let selectedEmission = 0;
let copiedEmission = null;
let selectedGraph = 'size';
let selectedNode = null;
let fxSaveTimer = null;
let draggingNode = null;
let deleteFunctionArmed = false;
let graphRedrawTimer = null;
const fx = (id) => /** @type {HTMLInputElement} */ (document.getElementById(id));
const fxInputIds = ['fx-count','fx-z-index','fx-shape','fx-speed-min','fx-speed-max','fx-acceleration','fx-drag','fx-direction-min','fx-direction-max','fx-rotation-min','fx-rotation-max','fx-rotation-speed-min','fx-rotation-speed-max','fx-life-min','fx-life-max','fx-pos-x','fx-pos-y','fx-glow','fx-image','fx-flipbook-size','fx-directional'];
const currentFunction = () => fxConfig.functions[fxConfig.selectedFunction];
const currentEmission = () => currentFunction().emissions[selectedEmission];
const effectLabel = name => String(name).replace(/\.fx\.json$/i, '');
const cloneDefaultCurve = key => JSON.parse(JSON.stringify(EMISSION_DEFAULT[key]));
function normalizeSquareColor(value) {
  const match = String(value).trim().match(/^#?([0-9a-f]{6})$/i);
  if (!match) throw new Error('Enter a six-digit hex color, for example #EEAEB6.');
  return `#${match[1].toUpperCase()}`;
}
function validateSquarePalette(colors, allowLegacy = false) {
  if (!colors || typeof colors !== 'object') {
    throw new Error(`Provide all ${SQUARE_COLOR_KEYS.length} square colors.`);
  }
  return Object.fromEntries(SQUARE_COLOR_KEYS.map(key => {
    if (!(key in colors)) {
      if (allowLegacy && OPTIONAL_SQUARE_COLOR_KEYS.has(key)) return [key, null];
      throw new Error(`Provide all ${SQUARE_COLOR_KEYS.length} square colors.`);
    }
    if (OPTIONAL_SQUARE_COLOR_KEYS.has(key) && colors[key] == null) return [key, null];
    return [key, normalizeSquareColor(colors[key])];
  }));
}
function activeSquareTheme() {
  return squareThemes.find(theme => theme.name === selectedSquareTheme) || squareThemes[0];
}
function saveSquareThemes() {
  const payload = { selected: selectedSquareTheme, themes: squareThemes };
  localStorage.setItem(SQUARE_THEMES_KEY, JSON.stringify(payload));
  window.cvfx.saveProjectSettings({ squareThemes: payload }).catch(error => {
    console.error('Could not save square themes to project data:', error);
  });
}
function applySquarePalette() {
  if (!pythonBackendReady) {
    const status = document.getElementById('square-color-status');
    if (status) status.textContent = `"${selectedSquareTheme}" selected; will apply when the detector is connected.`;
    return;
  }
  try {
    const colors = Object.fromEntries(SQUARE_COLOR_KEYS.map(key => {
      const hex = activeSquareTheme().colors[key];
      return [key, hex ? [1, 3, 5].map(offset => parseInt(hex.slice(offset, offset + 2), 16)) : null];
    }));
    const serialized = JSON.stringify(colors);
    if (serialized === lastAppliedSquarePalette) {
      const status = document.getElementById('square-color-status');
      if (status && !pendingSquarePaletteCommandId) {
        status.textContent = `Active theme: "${selectedSquareTheme}" — palette applied to move detection.`;
      }
      return;
    }
    const commandId = `palette-${Date.now()}`;
    window.cvfx.sendCommand({ type: 'set_pixel_palette', commandId, colors });
    lastAppliedSquarePalette = serialized;
    pendingSquarePaletteCommandId = commandId;
    const status = document.getElementById('square-color-status');
    if (status) status.textContent = `Applying "${selectedSquareTheme}" to move detection…`;
  } catch (error) {
    console.error('Could not apply square color theme:', error);
    const status = document.getElementById('square-color-status');
    if (status) status.textContent = `Could not apply "${selectedSquareTheme}"; see the log for details.`;
  }
}
function renderSquareTheme() {
  const select = /** @type {HTMLSelectElement} */ (document.getElementById('square-theme-select'));
  const rows = document.getElementById('square-color-list');
  const removeButton = /** @type {HTMLButtonElement} */ (document.getElementById('btn-delete-square-theme'));
  if (!select || !rows || !removeButton) return;
  select.replaceChildren(...squareThemes.map(theme => {
    const option = document.createElement('option');
    option.value = theme.name;
    option.textContent = theme.name;
    return option;
  }));
  if (!squareThemes.some(theme => theme.name === selectedSquareTheme)) selectedSquareTheme = squareThemes[0].name;
  select.value = selectedSquareTheme;
  removeButton.disabled = Boolean(activeSquareTheme().builtIn);
  rows.replaceChildren(...SQUARE_COLOR_KEYS.map((key, index) => {
    const row = document.createElement('div');
    row.className = 'square-color-row';
    const name = document.createElement('span');
    name.textContent = `${index + 1}. ${SQUARE_COLOR_LABELS[key]}`;
    const input = document.createElement('input');
    input.className = 'input input-sm square-color-input';
    input.type = 'text';
    input.spellcheck = false;
    input.autocomplete = 'off';
    input.value = activeSquareTheme().colors[key] || '';
    if (OPTIONAL_SQUARE_COLOR_KEYS.has(key)) input.placeholder = 'Pick exact color';
    input.dataset.colorKey = key;
    input.setAttribute('aria-label', `${SQUARE_COLOR_LABELS[key]} hex value`);
    const shortcut = index === 9 ? '0' : String(index + 1);
    input.title = `Color ${index + 1}: ${SQUARE_COLOR_LABELS[key]} (Ctrl+Alt+${shortcut} to sample screen color)`;
    const swatch = document.createElement('span');
    swatch.className = 'square-color-swatch';
    swatch.style.backgroundColor = activeSquareTheme().colors[key] || 'transparent';
    swatch.title = activeSquareTheme().colors[key]
      ? `${SQUARE_COLOR_LABELS[key]}: ${activeSquareTheme().colors[key]}`
      : `${SQUARE_COLOR_LABELS[key]}: not configured`;
    swatch.setAttribute('aria-hidden', 'true');
    const controls = document.createElement('div');
    controls.className = 'square-color-controls';
    const pickButton = document.createElement('button');
    pickButton.className = 'btn btn-secondary btn-sm square-color-pick';
    pickButton.type = 'button';
    pickButton.textContent = 'Pick';
    pickButton.setAttribute('aria-label', `Pick screen color for ${SQUARE_COLOR_LABELS[key]}`);
    pickButton.addEventListener('click', () => pickSquareColor(key));
    controls.append(swatch, input, pickButton);
    row.append(name, controls);
    return row;
  }));
}
async function loadSquareThemes() {
  try {
    const projectSettings = await window.cvfx.loadProjectSettings();
    const repoSaved = projectSettings && projectSettings.squareThemes && typeof projectSettings.squareThemes === 'object'
      ? projectSettings.squareThemes
      : null;
    const saved = repoSaved ? JSON.stringify(repoSaved) : localStorage.getItem(SQUARE_THEMES_KEY);
    if (saved) {
      try {
        const parsed = typeof saved === 'string' ? JSON.parse(saved) : saved;
        if (!Array.isArray(parsed.themes)) throw new Error('Theme list is invalid.');
        const loaded = parsed.themes
          .filter(theme => theme && typeof theme.name === 'string' && theme.name.trim())
          .map(theme => ({
            name: theme.name.trim(),
            builtIn: theme.name === 'Chess.com Pink',
            colors: validateSquarePalette(theme.colors, true),
          }));
        const builtIn = loaded.find(theme => theme.name === 'Chess.com Pink') ||
          { name: 'Chess.com Pink', builtIn: true, colors: { ...CHESS_COM_PALETTE } };
        squareThemes = [builtIn, ...loaded.filter(theme => theme.name !== builtIn.name)];
        selectedSquareTheme = squareThemes.some(theme => theme.name === parsed.selected)
          ? parsed.selected : builtIn.name;
      } catch (error) {
        console.error('Could not load saved square color themes; keeping the default theme:', error);
      }
    }
  } catch (error) {
    console.error('Could not load project-backed square color themes:', error);
  }
  renderSquareTheme();
  applySquarePalette();
}
async function pickSquareColor(key) {
  const status = document.getElementById('square-color-status');
  try {
    if (status) status.textContent = 'Click a color anywhere on your desktop, or press Esc to cancel.';
    const color = await window.cvfx.pickScreenColor();
    if (!color) {
      if (status) status.textContent = 'Screen color pick cancelled.';
      return;
    }
    const input = document.querySelector(`.square-color-input[data-color-key="${key}"]`);
    if (!input) return;
    input.value = color;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    if (status) status.textContent = `Picked ${color} for ${SQUARE_COLOR_LABELS[key]}.`;
  } catch (error) {
    if (error?.name !== 'AbortError') {
      console.error('Screen color picker failed:', error);
      if (status) status.textContent = `Color picker failed: ${error.message || error}`;
    }
  }
}
function updateSquareThemeColor(input) {
  const key = input.dataset.colorKey;
  if (!SQUARE_COLOR_KEYS.includes(key)) return;
  try {
    if (OPTIONAL_SQUARE_COLOR_KEYS.has(key) && !input.value.trim()) {
      activeSquareTheme().colors[key] = null;
      const swatch = input.closest('.square-color-controls')?.querySelector('.square-color-swatch');
      if (swatch) {
        swatch.style.backgroundColor = 'transparent';
        swatch.title = `${SQUARE_COLOR_LABELS[key]}: not configured`;
      }
      saveSquareThemes();
      applySquarePalette();
      return;
    }
    const color = normalizeSquareColor(input.value);
    input.value = color;
    activeSquareTheme().colors[key] = color;
    const swatch = input.closest('.square-color-controls')?.querySelector('.square-color-swatch');
    if (swatch) {
      swatch.style.backgroundColor = color;
      swatch.title = `${SQUARE_COLOR_LABELS[key]}: ${color}`;
    }
    saveSquareThemes();
    applySquarePalette();
  } catch {
    const status = document.getElementById('square-color-status');
    if (status) status.textContent = 'Invalid color. Use a six-digit hex value such as #EEAEB6.';
  }
}
function normalizeCurve(points, key) {
  const fallback = cloneDefaultCurve(key);
  if (!Array.isArray(points) || points.length === 0) return fallback;
  points.forEach(point => {
    point.t = Math.max(0, Math.min(1, Number(point.t) || 0));
    if (key === 'transparency') {
      const rawV = Number(point.v);
      point.v = Number.isFinite(rawV) ? (rawV > 1 ? Math.max(0, Math.min(1, rawV / 100)) : Math.max(0, Math.min(1, rawV))) : 0;
    } else if (key === 'size') {
      // v can be a legacy scalar or a new [min,max] pair.
      if (Array.isArray(point.v)) {
        point.v = [Math.max(0, Math.min(100, Number(point.v[0]) || 0)), Math.max(0, Math.min(100, Number(point.v[1]) || 0))];
      } else {
        const rawV = Math.max(0, Math.min(100, Number(point.v) || 0));
        point.v = [rawV, rawV]; // migrate scalar → [min,max]
      }
    } else if (key === 'color') {
      if (typeof point.v === 'string') point.v = hexToRgb(point.v);
      if (!Array.isArray(point.v) || point.v.length < 3) point.v = [255, 255, 255];
      else point.v = [Math.max(0, Math.min(255, Number(point.v[0]) || 0)), Math.max(0, Math.min(255, Number(point.v[1]) || 0)), Math.max(0, Math.min(255, Number(point.v[2]) || 0))];
    }
  });
  points.sort((a, b) => a.t - b.t);
  const normalized = [];
  points.forEach(point => {
    const last = normalized[normalized.length - 1];
    if (last && Math.abs(last.t - point.t) < 0.00001) normalized[normalized.length - 1] = point;
    else normalized.push(point);
  });
  if (normalized.length === 1) normalized.push({ t: normalized[0].t === 0 ? 1 : 0, v: Array.isArray(normalized[0].v) ? [...normalized[0].v] : normalized[0].v });
  normalized[0].t = 0;
  normalized[normalized.length - 1].t = 1;
  return normalized;
}
function normalizeEmissionCurves(emission) {
  ['size', 'transparency', 'color'].forEach(key => { emission[key] = normalizeCurve(emission[key], key); });
}

function migrateFxConfig(config) {
  // Version 1 stored one emitter directly. Convert it into a one-emission function.
  const migrated = !config?.functions ? { selectedFunction: 'default-capture.fx.json', functions: {
    'default-capture.fx.json': { emissions: [Object.assign(JSON.parse(JSON.stringify(EMISSION_DEFAULT)), config || {})] }
  }, movementDuration: 0.5 } : config;
  migrated.movementDuration = Math.max(0.05, Math.min(10, Number(migrated.movementDuration) || 0.5));
  Object.values(migrated.functions).forEach(fn => fn.emissions.forEach(emission => {
    const oldFlipbook = emission.flipbook || {};
    const legacyGridSize = Math.max(Number(oldFlipbook.columns) || 2, Number(oldFlipbook.rows) || 2);
    emission.flipbook = {
      size: Math.max(2, Math.min(16, Math.round(Number(oldFlipbook.size) || legacyGridSize))),
    };
    emission.color = (emission.color || []).map(point => ({ ...point, v: typeof point.v === 'string' ? hexToRgb(point.v) : point.v }));
    emission.glow = Math.max(0, Math.min(50, Number(emission.glow) || 0));
    emission.zIndex = Math.round(Number(emission.zIndex) || 0);
    // Older image emitters used their source colors by default. New and
    // migrated images tint from the color graph unless explicitly opted out.
    emission.imageColorMode = emission.imageColorMode === 'source' ? 'source' : 'tint';
    emission.acceleration = Math.max(0, Number(Array.isArray(emission.acceleration) ? emission.acceleration[0] : emission.acceleration) || 0);
    emission.drag = -Math.abs(Number(emission.drag) || 0);
    emission.directional = Boolean(emission.directional);
    normalizeEmissionCurves(emission);
  }));
  // Preset assignments live with the effect library so both renderer windows
  // receive one atomic configuration update.
  const fallback = migrated.selectedFunction in migrated.functions
    ? migrated.selectedFunction : Object.keys(migrated.functions)[0];
  migrated.selectedFunction = fallback;
  migrated.pieceEffects = migrated.pieceEffects && typeof migrated.pieceEffects === 'object' ? migrated.pieceEffects : {};
  PIECE_TYPES.forEach(piece => {
    const assignment = migrated.pieceEffects[piece] || {};
    // Version 2 stored one pair of effects per piece. Preserve those choices
    // for both teams when expanding the configuration to team-specific pairs.
    const forTeam = team => {
      const teamAssignment = assignment[team] || {};
      return {
        land: migrated.functions[teamAssignment.land] ? teamAssignment.land : (migrated.functions[assignment.land] ? assignment.land : fallback),
        capture: migrated.functions[teamAssignment.capture] ? teamAssignment.capture : (migrated.functions[assignment.capture] ? assignment.capture : fallback),
        trail: migrated.functions[teamAssignment.trail] ? teamAssignment.trail : null,
      };
    };
    migrated.pieceEffects[piece] = {
      white: forTeam('white'),
      black: forTeam('black'),
    };
  });
  migrated.teamEffects = migrated.teamEffects && typeof migrated.teamEffects === 'object' ? migrated.teamEffects : {};
  ['white', 'black'].forEach(team => {
    const key = `${team}Die`;
    migrated.teamEffects[key] = migrated.functions[migrated.teamEffects[key]] ? migrated.teamEffects[key] : fallback;
  });
  return migrated;
}
function isValidFxConfig(config) {
  return Boolean(config && typeof config === 'object' &&
    config.functions && typeof config.functions === 'object' &&
    Object.keys(config.functions).length > 0 &&
    Object.values(config.functions).every(fn =>
      fn && Array.isArray(fn.emissions) && fn.emissions.length > 0));
}
// Give a first-run configuration the same complete shape as saved configs.
fxConfig = migrateFxConfig(fxConfig);
function hexToRgb(hex) { const n = parseInt(String(hex).replace('#',''), 16); return [n >> 16 & 255, n >> 8 & 255, n & 255]; }
function copyEmission(indexToCopy) {
  readFxControls();
  const emissions = currentFunction().emissions;
  const srcIndex = typeof indexToCopy === 'number' ? indexToCopy : selectedEmission;
  if (!emissions[srcIndex]) return;
  const clone = JSON.parse(JSON.stringify(emissions[srcIndex]));
  const originalName = clone.name || `Emission ${srcIndex + 1}`;
  clone.name = `${originalName} (Copy)`;
  emissions.splice(srcIndex + 1, 0, clone);
  selectedEmission = srcIndex + 1;
  selectedNode = null;
  writeFxControls();
  saveFxLive();
}
function copyEmissionToClipboard(indexToCopy) {
  readFxControls();
  const emission = currentFunction().emissions[indexToCopy];
  if (!emission) return;
  copiedEmission = JSON.parse(JSON.stringify(emission));
  const pasteButton = document.getElementById('btn-paste-emission');
  pasteButton.disabled = false;
  pasteButton.title = `Paste "${copiedEmission.name || `Emission ${indexToCopy + 1}`}" into this effect`;
}
function pasteEmission() {
  if (!copiedEmission) return;
  readFxControls();
  const emissions = currentFunction().emissions;
  const pasted = JSON.parse(JSON.stringify(copiedEmission));
  const insertAt = selectedEmission + 1;
  emissions.splice(insertAt, 0, pasted);
  selectedEmission = insertAt;
  selectedNode = null;
  writeFxControls();
  saveFxLive();
}
function copyFunction() {
  readFxControls();
  const src = fxConfig.selectedFunction;
  const base = effectLabel(src);
  let number = 2, name = `${base} (Copy).fx.json`;
  while (fxConfig.functions[name]) name = `${base} (Copy ${number++}).fx.json`;
  fxConfig.functions[name] = JSON.parse(JSON.stringify(fxConfig.functions[src]));
  fxConfig.selectedFunction = name; selectedEmission = 0; selectedNode = null; deleteFunctionArmed = false;
  writeFxControls(); saveFxLive();
}

function refreshFxSelectors() {
  const functionSelect = fx('fx-function'), emissionSelect = fx('fx-emission');
  functionSelect.value = effectLabel(fxConfig.selectedFunction);
  const emissions = currentFunction().emissions;
  selectedEmission = Math.max(0, Math.min(selectedEmission, emissions.length - 1));
  emissionSelect.value = emissions[selectedEmission].name || `Emission ${selectedEmission + 1}`;
  document.getElementById('btn-delete-emission').disabled = emissions.length <= 1;
  const deleteFunction = document.getElementById('btn-delete-function');
  deleteFunction.disabled = Object.keys(fxConfig.functions).length <= 1;
  deleteFunction.textContent = deleteFunctionArmed ? 'Click again to delete' : 'Delete effect';
  deleteFunction.classList.toggle('confirm', deleteFunctionArmed);
  const list = document.getElementById('fx-function-list');
  list.innerHTML = Object.keys(fxConfig.functions).map(name => `<button class="fx-function-item ${name === fxConfig.selectedFunction ? 'active' : ''}" data-name="${name}">${effectLabel(name)}</button>`).join('');
  list.querySelectorAll('.fx-function-item').forEach(button => button.addEventListener('click', () => {
    readFxControls(); fxConfig.selectedFunction = button.dataset.name; selectedEmission = 0; selectedNode = null; deleteFunctionArmed = false; writeFxControls(); saveFxLive();
  }));
  const emissionList = document.getElementById('fx-emission-list');
  emissionList.innerHTML = emissions.map((emission, index) => `
    <div class="fx-emission-chip ${index === selectedEmission ? 'active' : ''}">
      <button class="fx-emission-item" data-index="${index}">${emission.name || `Emission ${index + 1}`}</button>
      <button class="fx-emission-copy" data-index="${index}" title="Copy emission for use in another effect" aria-label="Copy emission for use in another effect">📋</button>
    </div>
  `).join('');
  emissionList.querySelectorAll('.fx-emission-item').forEach(button => button.addEventListener('click', () => {
    readFxControls(); selectedEmission = Number(button.dataset.index); selectedNode = null; writeFxControls();
  }));
  emissionList.querySelectorAll('.fx-emission-copy').forEach(button => button.addEventListener('click', (e) => {
    e.stopPropagation();
    copyEmission(Number(button.dataset.index));
  }));
  renderPieceEffectAssignments();
}

function renderPieceEffectAssignments() {
  const list = document.getElementById('piece-effect-list');
  if (!list) return;
  const names = Object.keys(fxConfig.functions);
  const options = names.map(name => `<option value="${name}">${effectLabel(name)}</option>`).join('');
  const trailOptions = `<option value="">None</option>${options}`;
  list.innerHTML = ['white', 'black'].map(team => `
    <section class="piece-effect-team" aria-label="${team} piece effects">
      <h4 class="piece-effect-team-title">${team[0].toUpperCase()}${team.slice(1)} pieces</h4>
      <div class="piece-effect-head" aria-hidden="true"><span>Piece</span><span>Land</span><span>Capture</span><span>Trail</span></div>
      ${PIECE_TYPES.map(piece => `<label class="piece-effect-row"><span>${piece[0].toUpperCase()}${piece.slice(1)}</span><select class="select" data-piece="${piece}" data-team="${team}" data-effect-kind="land">${options}</select><select class="select" data-piece="${piece}" data-team="${team}" data-effect-kind="capture">${options}</select>${['queen', 'rook'].includes(piece) ? `<select class="select" aria-label="${team} ${piece} trail effect" data-piece="${piece}" data-team="${team}" data-effect-kind="trail">${trailOptions}</select>` : '<span class="piece-effect-empty" aria-hidden="true">—</span>'}</label>`).join('')}
    </section>
  `).join('') + `
    <section class="piece-death-effects" aria-label="Piece defeat effects">
      <h4>Defeat effects</h4>
      <label>White die<select class="select" data-team-death="white">${options}</select></label>
      <label>Black die<select class="select" data-team-death="black">${options}</select></label>
    </section>
  `;
  list.querySelectorAll('select').forEach(select => {
    if (select.dataset.teamDeath) {
      const key = `${select.dataset.teamDeath}Die`;
      select.value = fxConfig.teamEffects[key];
      select.addEventListener('change', () => {
        fxConfig.teamEffects[key] = select.value;
        saveFxLive();
      });
      return;
    }
    const assignment = fxConfig.pieceEffects[select.dataset.piece][select.dataset.team];
    select.value = assignment[select.dataset.effectKind] || '';
    select.addEventListener('change', () => {
      fxConfig.pieceEffects[select.dataset.piece][select.dataset.team][select.dataset.effectKind] = select.value;
      saveFxLive();
    });
  });
}

function replacePieceEffectReference(from, to) {
  PIECE_TYPES.forEach(piece => {
    const assignment = fxConfig.pieceEffects?.[piece];
    if (!assignment) return;
    ['white', 'black'].forEach(team => {
      if (assignment[team]?.land === from) assignment[team].land = to;
      if (assignment[team]?.capture === from) assignment[team].capture = to;
      if (assignment[team]?.trail === from) assignment[team].trail = to;
    });
  });
  ['white', 'black'].forEach(team => {
    const key = `${team}Die`;
    if (fxConfig.teamEffects?.[key] === from) fxConfig.teamEffects[key] = to;
  });
}

function numberFx(id) { return Number(fx(id).value) || 0; }
function readFxControls() {
  const emission = currentEmission();
  emission.count = Math.max(1, Math.round(numberFx('fx-count')));
  emission.zIndex = Math.round(numberFx('fx-z-index'));
  emission.shape = fx('fx-shape').value;
  emission.speed = [numberFx('fx-speed-min'), numberFx('fx-speed-max')];
  emission.acceleration = Math.max(0, numberFx('fx-acceleration'));
  emission.drag = -Math.abs(numberFx('fx-drag'));
  emission.direction = [numberFx('fx-direction-min'), numberFx('fx-direction-max')];
  emission.directional = Boolean(fx('fx-directional').checked);
  emission.rotation = [numberFx('fx-rotation-min'), numberFx('fx-rotation-max')];
  emission.rotationSpeed = [numberFx('fx-rotation-speed-min'), numberFx('fx-rotation-speed-max')];
  emission.lifetime = [Math.max(.01, numberFx('fx-life-min')), Math.max(.01, numberFx('fx-life-max'))];
  emission.position = { x: numberFx('fx-pos-x'), y: numberFx('fx-pos-y') };
  emission.glow = Math.max(0, Math.min(50, numberFx('fx-glow')));
  emission.imageId = fx('fx-image').value.trim();
  emission.imageColorMode = fx('fx-source-image').checked ? 'source' : 'tint';
  emission.flipbook = { size: Math.max(2, Math.min(16, Math.round(numberFx('fx-flipbook-size')) || 2)) };
}
function writeFxControls() {
  const emission = currentEmission();
  const set = (id, value) => { fx(id).value = String(value); };
  set('fx-movement-duration', fxConfig.movementDuration);
  refreshFxSelectors();
  set('fx-count', emission.count); set('fx-z-index', emission.zIndex || 0); set('fx-shape', emission.shape); set('fx-speed-min',emission.speed[0]); set('fx-speed-max',emission.speed[1]); set('fx-acceleration',emission.acceleration || 0); set('fx-drag',Math.abs(emission.drag || 0));
  set('fx-direction-min',emission.direction[0]); set('fx-direction-max',emission.direction[1]); set('fx-rotation-min',emission.rotation[0]); set('fx-rotation-max',emission.rotation[1]);
  set('fx-rotation-speed-min',emission.rotationSpeed[0]); set('fx-rotation-speed-max',emission.rotationSpeed[1]); set('fx-life-min',emission.lifetime[0]); set('fx-life-max',emission.lifetime[1]);
  set('fx-pos-x',emission.position.x); set('fx-pos-y',emission.position.y); set('fx-glow',emission.glow || 0); set('fx-image',emission.imageId || ''); fx('fx-source-image').checked = emission.imageColorMode === 'source'; fx('fx-directional').checked = Boolean(emission.directional); set('fx-flipbook-size',emission.flipbook.size);
  updateImageFieldVisibility();
  drawFxGraph();
}
function updateImageFieldVisibility() {
  const isImage = ['image', 'flipbook'].includes(fx('fx-shape').value);
  document.getElementById('fx-image-fields').hidden = !isImage;
  document.getElementById('fx-flipbook-fields').hidden = fx('fx-shape').value !== 'flipbook';
}
function flushFxSave() {
  clearTimeout(fxSaveTimer); fxSaveTimer = null;
  if (!fxConfigReady) {
    if (!fxConfigSaveBlockedLogged) {
      console.error('Particle effects were not saved: no valid saved effect configuration was loaded.');
      fxConfigSaveBlockedLogged = true;
    }
    return;
  }
  readFxControls();
  fxConfig.movementDuration = Math.max(0.05, Math.min(10, Number(fx('fx-movement-duration').value) || 0.5));
  fx('fx-movement-duration').value = String(fxConfig.movementDuration);
  normalizeEmissionCurves(currentEmission());
  const serialized = JSON.stringify(fxConfig);
  const previous = localStorage.getItem(FX_CONFIG_KEY);
  if (previous) {
    try {
      const previousConfig = migrateFxConfig(JSON.parse(previous));
      if (isValidFxConfig(previousConfig)) localStorage.setItem(FX_CONFIG_BACKUP_KEY, previous);
    } catch (error) {
      console.error('Could not validate the previous particle-effects config for backup:', error);
    }
  }
  localStorage.setItem(FX_CONFIG_KEY, serialized);
  window.cvfx.saveProjectSettings({ fxConfig }).catch(error => {
    console.error('Could not save particle effects to project data:', error);
  });
  return window.cvfx.setEffectConfig(fxConfig);
}
function saveFxLive(immediate = false) {
  if (!fxConfigReady) {
    flushFxSave();
    return;
  }
  readFxControls(); drawFxGraph();
  clearTimeout(fxSaveTimer);
  if (immediate) return flushFxSave();
  fxSaveTimer = setTimeout(flushFxSave, 90);
}
function drawFxGraph(skipEditor = false) {
  const svg = document.getElementById('fx-graph'), graph = selectedGraph;
  let points = currentEmission()[graph].map((p,index) => ({...p,index})).sort((a,b) => a.t-b.t);
  const w = 640, h = 260;
  // The lifetime plot is the entire graph surface: t=0 and t=1 are the
  // literal left and right edges, and 0/100 are the literal bottom and top.
  if (points.length) {
    currentEmission()[graph][points[0].index].t = 0;
    currentEmission()[graph][points[points.length - 1].index].t = 1;
    points = currentEmission()[graph].map((p,index) => ({...p,index})).sort((a,b) => a.t-b.t);
  }
  // For size, v is [min,max]; use midpoint for display/graph height.
  const sizeDisplayVal = v => Array.isArray(v) ? (Number(v[0]) + Number(v[1])) / 2 : Number(v);
  const displayValue = value => graph === 'transparency' ? Number(value) * 100 : (graph === 'size' ? sizeDisplayVal(value) : Number(value));
  const storedValue = value => graph === 'transparency' ? value / 100 : (graph === 'size' ? [value, value] : value);
  const x = p => Math.max(0, Math.min(1, Number(p.t))) * w;
  const y = p => graph === 'color' ? h / 2 : (1 - Math.max(0, Math.min(100, displayValue(p.v))) / 100) * h;
  const color = graph === 'color' ? p => `rgb(${p.v.join(',')})` : () => 'var(--accent-green)';
  // preserveAspectRatio="none" keeps the curve fitted to the available area.
  // Compensate in viewBox units so a node remains a circle on every window size.
  const bounds = svg.getBoundingClientRect();
  const radiusX = Math.max(.5, 7 * w / Math.max(1, bounds.width)), radiusY = Math.max(.5, 7 * h / Math.max(1, bounds.height));
  const axes = graph === 'color' ? '' : `<text x="10" y="14" class="graph-axis-label">100</text><text x="10" y="${h-6}" class="graph-axis-label">0</text>`;
  svg.innerHTML = axes + `<path class="curve" d="M ${points.map(p => `${x(p)},${y(p)}`).join(' L ')}"></path>` + points.map(p => `<ellipse class="point ${selectedNode === p.index ? 'selected' : ''}" data-index="${p.index}" cx="${x(p)}" cy="${y(p)}" rx="${radiusX}" ry="${radiusY}" fill="${color(p)}"></ellipse>`).join('');
  document.getElementById('fx-graph-title').textContent = `${graph === 'color' ? 'Color (RGB)' : graph[0].toUpperCase()+graph.slice(1)} over lifetime`;
  const pointFromEvent = event => {
    // SVG's coordinate transform accounts for borders, scaling and any
    // aspect-ratio adjustment, unlike manually dividing by client width.
    const ctm = svg.getScreenCTM();
    if (!ctm) return { t: 0, v: 0 };
    const mouse = svg.createSVGPoint(); mouse.x = event.clientX; mouse.y = event.clientY;
    const local = mouse.matrixTransform(ctm.inverse());
    return {
      t: Math.max(0, Math.min(1, local.x / w)),
      v: Math.max(0, Math.min(100, (1-local.y/h) * 100)),
    };
  };
  svg.onpointerdown = event => {
    const target = event.target;
    if (target.classList.contains('point')) {
      selectedNode = Number(target.dataset.index);
      const ordered = currentEmission()[graph].map((node, index) => ({node,index})).sort((a,b) => a.node.t-b.node.t);
      const isEndpoint = ordered[0].index === selectedNode || ordered[ordered.length - 1].index === selectedNode;
      draggingNode = { index: selectedNode, lockX: isEndpoint, node: currentEmission()[graph][selectedNode], didMove: false };
      svg.setPointerCapture(event.pointerId);
      event.preventDefault();
      drawFxGraph();
      renderNodeEditor();
      return;
    }
    const point = pointFromEvent(event), v = graph === 'color' ? [255,255,255] : storedValue(point.v);
    currentEmission()[graph].push({t:point.t,v});
    normalizeEmissionCurves(currentEmission());
    selectedNode = currentEmission()[graph].findIndex(node => Math.abs(node.t - point.t) < 0.001);
    if (selectedNode < 0) selectedNode = currentEmission()[graph].length - 1;
    drawFxGraph();
    renderNodeEditor();
    flushFxSave();
    redrawGraphAfterLayout();
  };
  svg.onpointermove = event => {
    if (draggingNode === null || !draggingNode.node) return;
    draggingNode.didMove = true;
    const point = pointFromEvent(event), node = draggingNode.node;
    if (!draggingNode.lockX) node.t = Math.max(0.001, Math.min(0.999, point.t));
    if (graph !== 'color') {
      const sv = storedValue(point.v);
      if (graph === 'size' && Array.isArray(node.v)) {
        // Keep the min/max spread when dragging; shift both endpoints by midpoint change.
        const mid = (node.v[0] + node.v[1]) / 2, spread = node.v[1] - node.v[0];
        const newMid = Array.isArray(sv) ? sv[0] : sv;
        node.v = [Math.max(0, Math.min(100, newMid - spread / 2)), Math.max(0, Math.min(100, newMid + spread / 2))];
      } else {
        node.v = sv;
      }
    }
    drawFxGraph(true);
    // Sync size min/max inputs if present
    if (graph === 'size' && Array.isArray(node.v)) {
      const minInp = document.querySelector('#fx-node-editor .node-size-min');
      const maxInp = document.querySelector('#fx-node-editor .node-size-max');
      if (minInp && document.activeElement !== minInp) minInp.value = String(Math.round(node.v[0] * 100) / 100);
      if (maxInp && document.activeElement !== maxInp) maxInp.value = String(Math.round(node.v[1] * 100) / 100);
    }
    const valInput = document.querySelector('#fx-node-editor .node-value');
    if (valInput && document.activeElement !== valInput && graph === 'transparency') {
      valInput.value = String(Math.round(Number(node.v) * 10000) / 100);
    }
    const lifetimeLabel = document.querySelector('#fx-node-editor > span');
    if (lifetimeLabel) {
      lifetimeLabel.textContent = `Node at ${(node.t * 100).toFixed(0)}% lifetime`;
    }
    saveFxLive();
  };
  svg.onpointerup = svg.onpointercancel = event => {
    if (draggingNode !== null) {
      if (svg.hasPointerCapture(event.pointerId)) svg.releasePointerCapture(event.pointerId);
      const targetNode = draggingNode.node;
      const targetT = targetNode ? targetNode.t : 0;
      if (draggingNode.didMove) {
        normalizeEmissionCurves(currentEmission());
        let closestIdx = 0, minDist = Infinity;
        currentEmission()[graph].forEach((p, idx) => {
          const dist = Math.abs(p.t - targetT);
          if (dist < minDist) {
            minDist = dist;
            closestIdx = idx;
          }
        });
        selectedNode = closestIdx;
      }
      draggingNode = null;
      drawFxGraph();
      renderNodeEditor();
      flushFxSave();
    }
  };
  if (!skipEditor) renderNodeEditor(true);
}
function redrawGraphAfterLayout() {
  cancelAnimationFrame(graphRedrawTimer);
  graphRedrawTimer = requestAnimationFrame(() => {
    drawFxGraph();
    requestAnimationFrame(drawFxGraph);
  });
}
function renderNodeEditor(skipIfFocused = false) {
  const host = document.getElementById('fx-node-editor'), graph = selectedGraph;
  // Dynamic accessor — always retrieves the live array entry even after
  // normalizeEmissionCurves replaces array contents.
  const getNode = () =>
    (selectedNode !== null && currentEmission()[graph])
      ? currentEmission()[graph][selectedNode]
      : null;
  if (!getNode()) {
    host.textContent = 'Click the graph to create a node, or select a node to edit its value.';
    return;
  }
  if (skipIfFocused && document.activeElement && host.contains(document.activeElement)) {
    return;
  }
  const node0 = getNode();
  const isColor = graph === 'color';
  const rgbToHex = rgb => '#' + rgb.map(c => Math.max(0, Math.min(255, Number(c) || 0)).toString(16).padStart(2, '0')).join('');
  const initHex = isColor && Array.isArray(node0.v) ? rgbToHex(node0.v) : '#ffffff';
  const initVal = graph === 'transparency'
    ? Math.round(Number(node0.v) * 10000) / 100
    : Math.round(Number(node0.v) * 100) / 100;
  const valueInputs = isColor
    ? `<input class="node-color-picker" type="color" value="${initHex}" title="Choose color"><label>Hex<input class="input input-sm node-hex" value="${initHex}" spellcheck="false"></label>` +
      ['R','G','B'].map((label, i) => `<label>${label}<input class="input input-sm node-value" data-channel="${i}" type="number" min="0" max="255" value="${Array.isArray(node0.v) ? node0.v[i] : 255}"></label>`).join('')
    : `<label>Value<input class="input input-sm node-value" type="number" min="0" max="100" step=".01" value="${Number.isFinite(initVal) ? initVal : 0}"></label>`;
  host.innerHTML = `<span>Node at ${(node0.t * 100).toFixed(0)}% lifetime</span>${valueInputs}<button id="btn-delete-node" class="btn btn-ghost btn-sm">Delete node</button>`;
  host.querySelectorAll('input[type="number"]').forEach(inp => inp.addEventListener('focus', () => inp.select()));

  // ── Color graph: R/G/B inputs + hex field + color picker ────────────────
  if (isColor) {
    const picker = host.querySelector('.node-color-picker');
    const hexInput = host.querySelector('.node-hex');
    const channelInputs = /** @type {NodeListOf<HTMLInputElement>} */ (host.querySelectorAll('.node-value'));

    const syncPickerFromChannels = () => {
      const n = getNode(); if (!n || !Array.isArray(n.v)) return;
      picker.value = rgbToHex(n.v);
      hexInput.value = rgbToHex(n.v);
    };
    const syncChannelsFromHex = (hex) => {
      const n = getNode(); if (!n) return;
      n.v = hexToRgb(hex);
      channelInputs.forEach((inp, i) => { inp.value = String(n.v[i]); });
      picker.value = hex;
    };

    channelInputs.forEach(inp => {
      const onInput = () => {
        const n = getNode(); if (!n) return;
        if (!Array.isArray(n.v)) n.v = [255, 255, 255];
        n.v[Number(inp.dataset.channel)] = Math.max(0, Math.min(255, Number(inp.value) || 0));
        syncPickerFromChannels();
        drawFxGraph(true);
        saveFxLive();
      };
      inp.addEventListener('input', onInput);
      inp.addEventListener('change', onInput);
    });

    picker.addEventListener('input', e => {
      syncChannelsFromHex(e.target.value);
      drawFxGraph(true);
      saveFxLive();
    });
    picker.addEventListener('change', e => {
      syncChannelsFromHex(e.target.value);
      drawFxGraph(true);
      saveFxLive();
    });

    hexInput.addEventListener('input', () => {
      const raw = hexInput.value.trim();
      const hex = raw.startsWith('#') ? raw : '#' + raw;
      if (/^#[0-9a-f]{6}$/i.test(hex)) {
        syncChannelsFromHex(hex);
        drawFxGraph(true);
        saveFxLive();
      }
    });
    hexInput.addEventListener('blur', () => {
      const raw = hexInput.value.trim();
      const hex = raw.startsWith('#') ? raw : '#' + raw;
      if (/^#[0-9a-f]{6}$/i.test(hex)) {
        syncChannelsFromHex(hex);
      } else {
        // Revert to current node colour on invalid input
        const n = getNode();
        if (n && Array.isArray(n.v)) hexInput.value = rgbToHex(n.v);
      }
    });
  } else if (graph === 'size') {
    // ── Size input: [min, max] range per node ─────────────────────────────
    const node0v = Array.isArray(node0.v) ? node0.v : [node0.v, node0.v];
    // Replace the generic single-input HTML with two labelled inputs
    host.innerHTML = `<span>Node at ${(node0.t * 100).toFixed(0)}% lifetime</span>` +
      `<label>Min<input class="input input-sm node-size-min" type="number" min="0" max="100" step=".01" value="${node0v[0]}"></label>` +
      `<label>Max<input class="input input-sm node-size-max" type="number" min="0" max="100" step=".01" value="${node0v[1]}"></label>` +
      `<button id="btn-delete-node" class="btn btn-ghost btn-sm">Delete node</button>`;
    host.querySelectorAll('input[type="number"]').forEach(inp => inp.addEventListener('focus', () => inp.select()));
    const minInput = /** @type {HTMLInputElement} */ (host.querySelector('.node-size-min'));
    const maxInput = /** @type {HTMLInputElement} */ (host.querySelector('.node-size-max'));
    const writeSize = () => {
      const n = getNode(); if (!n) return;
      const lo = Math.max(0, Math.min(100, Number(minInput.value) || 0));
      const hi = Math.max(0, Math.min(100, Number(maxInput.value) || 0));
      n.v = [lo, hi];
    };
    const syncSize = () => {
      const n = getNode(); if (!n || !Array.isArray(n.v)) return;
      minInput.value = String(Math.round(n.v[0] * 100) / 100);
      maxInput.value = String(Math.round(n.v[1] * 100) / 100);
    };
    [minInput, maxInput].forEach(inp => {
      inp.addEventListener('input', () => { writeSize(); drawFxGraph(true); saveFxLive(); });
      inp.addEventListener('change', () => { writeSize(); syncSize(); drawFxGraph(true); saveFxLive(); });
      inp.addEventListener('blur', syncSize);
    });
  } else {
    // ── Transparency input ─────────────────────────────────────────────────
    const valInput = /** @type {HTMLInputElement} */ (host.querySelector('.node-value'));
    const readRaw = () => {
      const n = getNode(); if (!n) return 0;
      return Math.round(Number(n.v) * 10000) / 100;
    };
    const writeRaw = (displayVal) => {
      const n = getNode(); if (!n) return;
      n.v = Math.max(0, Math.min(1, (Number(displayVal) || 0) / 100));
    };
    valInput.addEventListener('input', () => { writeRaw(valInput.value); drawFxGraph(true); saveFxLive(); });
    valInput.addEventListener('change', () => { writeRaw(valInput.value); valInput.value = String(readRaw()); drawFxGraph(true); saveFxLive(); });
    valInput.addEventListener('blur', () => { valInput.value = String(readRaw()); });
  }

  const deleteNode = host.querySelector('#btn-delete-node');
  deleteNode.disabled = currentEmission()[graph].length <= 2;
  deleteNode.addEventListener('click', () => {
    if (currentEmission()[graph].length <= 2) return;
    currentEmission()[graph].splice(selectedNode, 1);
    normalizeEmissionCurves(currentEmission());
    selectedNode = null;
    drawFxGraph();
    renderNodeEditor();
    flushFxSave();
  });
}

// Phase 2/3 Board state
let currentOrientation = 'white_bottom';
let lockedBoard = null;
let currentCandidates = [];
let selectedCandidate = null;
let latestFrameMeta = null;
let currentOccupancy = {};
let lastMoveScanLogTime = 0;

// stat cells
const statState       = document.getElementById('stat-state');
const statMonitor     = document.getElementById('stat-monitor');
const statResolution  = document.getElementById('stat-resolution');
const statFps         = document.getElementById('stat-fps');
const statCaptureMs   = document.getElementById('stat-capture-ms');
const statTimestamp   = document.getElementById('stat-timestamp');

// ─── Logging ──────────────────────────────────────────────────────────────────
/**
 * @param {string} msg
 * @param {'info'|'warn'|'error'|'ok'|'debug'} level
 */
function log(msg, level = 'info') {
  logCount++;
  const entry = document.createElement('div');
  entry.className = `log-entry level-${level}`;

  const now = new Date();
  const ts = `${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')}:${now.getSeconds().toString().padStart(2,'0')}`;
  entry.innerHTML = `<span class="log-time">${ts}</span>${escHtml(msg)}`;

  elLogList.appendChild(entry);

  // Trim old entries
  while (elLogList.children.length > MAX_LOG_ENTRIES) {
    elLogList.removeChild(elLogList.firstChild);
  }

  // Auto-scroll
  const container = elLogList.parentElement;
  if (container) container.scrollTop = container.scrollHeight;
}

function escHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ─── Python status ────────────────────────────────────────────────────────────
function setPythonOnline(online) {
  // Connectivity remains useful internally, but the header communicates the
  // state the user controls: whether the effect app is active.
  elPythonStatus.dataset.backendReady = String(Boolean(online));
  pythonBackendReady = Boolean(online);
  if (!pythonBackendReady) {
    lastAppliedSquarePalette = '';
    pendingSquarePaletteCommandId = '';
  }
  if (pythonBackendReady) applySquarePalette();
}

// ─── App state badge ──────────────────────────────────────────────────────────
const STATE_CLASSES = {
  NO_BOARD:        'state-no-board',
  SEARCHING:       'state-searching',
  CANDIDATE_FOUND: 'state-searching',
  BOARD_LOCKED:    'state-locked',
  TRACKING:        'state-locked',
  REACQUIRING:     'state-reacquire',
  ERROR:           'state-error',
};

function setAppState(state) {
  const cls = STATE_CLASSES[state] || 'state-no-board';
  elStateBadge.className = `state-badge ${cls}`;
  elStateLabel.textContent = state.replace(/_/g, ' ');
  if (statState) statState.textContent = state;
}

// ─── Error banner ─────────────────────────────────────────────────────────────
function showError(msg) {
  elLastErrorText.textContent = msg;
  elLastError.classList.remove('hidden');
}

function clearError() {
  elLastError.classList.add('hidden');
}

// ─── Monitor list ─────────────────────────────────────────────────────────────
function populateMonitorSelect(monitors) {
  elMonitorSelect.innerHTML = '';
  monitors.forEach((m) => {
    const opt = document.createElement('option');
    opt.value = String(m.index);
    const label = m.isPrimary ? `★ Monitor ${m.index + 1} (Primary)` : `Monitor ${m.index + 1}`;
    const details = `${m.width}×${m.height}`;
    opt.textContent = `${label} – ${details}`;
    elMonitorSelect.appendChild(opt);
  });

  // Default to primary
  const primary = monitors.find(m => m.isPrimary);
  if (primary) {
    elMonitorSelect.value = String(primary.index);
    currentMonitorIndex = primary.index;
  }

  if (statMonitor) statMonitor.textContent = `Monitor ${currentMonitorIndex}`;
  log(`Monitors updated: ${monitors.length} found`, 'ok');
}

// ─── Frame preview ────────────────────────────────────────────────────────────
const ctx = elPreviewCanvas.getContext('2d');
let previewImage = new Image();

function showPreview(jpegBase64, frameInfo) {
  latestFrameMeta = frameInfo;
  elPreviewPh.style.display = 'none';
  elPreviewCanvas.style.display = 'block';

  previewImage.onload = () => {
    // Fit canvas to container
    const container = elPreviewCanvas.parentElement;
    const maxW = container.clientWidth;
    const maxH = container.clientHeight;
    const scale = Math.min(maxW / previewImage.naturalWidth, maxH / previewImage.naturalHeight, 1);
    elPreviewCanvas.width  = Math.round(previewImage.naturalWidth  * scale);
    elPreviewCanvas.height = Math.round(previewImage.naturalHeight * scale);
    ctx.drawImage(previewImage, 0, 0, elPreviewCanvas.width, elPreviewCanvas.height);

    // Phase 2: Render Board Grid Overlay if board is locked or candidate selected
    drawBoardOverlay(ctx, elPreviewCanvas.width, elPreviewCanvas.height, frameInfo);
  };
  previewImage.src = `data:image/jpeg;base64,${jpegBase64}`;

  // Update stats
  if (frameInfo) {
    const ts = new Date(frameInfo.timestamp).toLocaleTimeString();
    if (statResolution)  statResolution.textContent  = `${frameInfo.width}×${frameInfo.height}`;
    if (statTimestamp)   statTimestamp.textContent   = ts;
    if (statCaptureMs)   statCaptureMs.textContent   = `${frameInfo.captureDurationMs.toFixed(1)} ms`;
  }
}

function drawBoardOverlay(ctx, canvasW, canvasH, frameInfo) {
  if (!frameInfo || !frameInfo.width || !frameInfo.height) return;

  const target = lockedBoard?.rect || selectedCandidate?.rect;
  if (!target) return;

  const scaleX = canvasW / frameInfo.width;
  const scaleY = canvasH / frameInfo.height;

  const bx = target.left * scaleX;
  const by = target.top * scaleY;
  const bw = target.width * scaleX;
  const bh = target.height * scaleY;

  ctx.save();

  // Outer border
  ctx.strokeStyle = lockedBoard ? '#3ddc84' : '#38bdf8';
  ctx.lineWidth = 2;
  ctx.strokeRect(bx, by, bw, bh);

  // 8x8 Grid lines
  ctx.strokeStyle = lockedBoard ? 'rgba(61, 220, 132, 0.45)' : 'rgba(56, 189, 248, 0.45)';
  ctx.lineWidth = 1;

  const sqW = bw / 8.0;
  const sqH = bh / 8.0;

  for (let i = 1; i < 8; i++) {
    // Vertical line
    ctx.beginPath();
    ctx.moveTo(bx + i * sqW, by);
    ctx.lineTo(bx + i * sqW, by + bh);
    ctx.stroke();

    // Horizontal line
    ctx.beginPath();
    ctx.moveTo(bx, by + i * sqH);
    ctx.lineTo(bx + bw, by + i * sqH);
    ctx.stroke();
  }

  // Draw corner & key square labels if board is locked
  if (lockedBoard && lockedBoard.squares) {
    ctx.font = '10px JetBrains Mono, monospace';
    ctx.textBaseline = 'middle';
    ctx.textAlign = 'center';

    const keySquares = ['a8', 'h8', 'a1', 'h1', 'e4', 'd4', 'e5', 'd5'];
    lockedBoard.squares.forEach((sq) => {
      const scx = sq.imageCenter.x * scaleX;
      const scy = sq.imageCenter.y * scaleY;
      const occ = currentOccupancy[sq.name];

      // Phase 3: Occupancy marker
      if (occ && occ.status === 'OCCUPIED') {
        ctx.beginPath();
        ctx.arc(scx, scy, 5, 0, Math.PI * 2);
        if (occ.color === 'WHITE') {
          ctx.fillStyle = '#ffffff';
          ctx.fill();
          ctx.strokeStyle = '#000000';
          ctx.lineWidth = 1;
          ctx.stroke();
        } else if (occ.color === 'BLACK') {
          ctx.fillStyle = '#0f172a';
          ctx.fill();
          ctx.strokeStyle = '#e2e8f0';
          ctx.lineWidth = 1;
          ctx.stroke();
        } else {
          ctx.fillStyle = '#f59e0b';
          ctx.fill();
        }
      }

      if (keySquares.includes(sq.name) || (elDebugToggle && elDebugToggle.checked)) {
        ctx.fillStyle = 'rgba(0, 0, 0, 0.65)';
        ctx.fillRect(scx - 11, scy - 14, 22, 12);
        ctx.fillStyle = '#3ddc84';
        ctx.fillText(sq.name, scx, scy - 8);
      }
    });
  }

  ctx.restore();
}

function renderOccupancyGrid(squares) {
  if (!elOccupancyGrid || !lockedBoard?.squares) return;
  elOccupancyGrid.innerHTML = '';
  [...lockedBoard.squares]
    .sort((a, b) => a.row - b.row || a.col - b.col)
    .forEach((square) => {
      const observation = squares[square.name];
      const cell = document.createElement('div');
      cell.className = `occupancy-cell ${observation?.status === 'OCCUPIED' ? 'occupied' : ''} ${observation?.isStable ? '' : 'unstable'}`;
      cell.title = observation
        ? `${square.name}: ${observation.status}, ${Math.round(observation.confidence * 100)}% confidence`
        : `${square.name}: awaiting data`;
      cell.textContent = `${square.name} ${observation ? Math.round(observation.confidence * 100) : '—'}`;
      elOccupancyGrid.appendChild(cell);
    });
}

// ─── Handle Python messages ───────────────────────────────────────────────────
function handlePythonMessage(msg) {
  clearError();

  switch (msg.type) {
    case 'ready':
      setPythonOnline(true);
      log(`Python backend ready (v${msg.version}, Python ${msg.pythonVersion})`, 'ok');
      break;

    case 'monitor_list':
      populateMonitorSelect(msg.monitors);
      break;

    case 'frame_status':
      if (!captureRunning) {
        captureRunning = true;
        updateEffectsControls();
      }
      if (statFps) statFps.textContent = `${msg.avgFps.toFixed(1)}`;
      if (msg.frame) {
        if (statResolution)  statResolution.textContent  = `${msg.frame.width}×${msg.frame.height}`;
        if (statCaptureMs)   statCaptureMs.textContent   = `${msg.frame.captureDurationMs.toFixed(1)} ms`;
        if (statTimestamp)   statTimestamp.textContent   = new Date(msg.frame.timestamp).toLocaleTimeString();
      }
      elPreviewStats.textContent = `${msg.avgFps.toFixed(1)} fps · ${msg.frame?.captureDurationMs?.toFixed(1) ?? '?'} ms`;
      break;

    case 'move_scan_debug': {
      const highlights = msg.highlights?.length ? msg.highlights.join(', ') : 'none';
      const targets = msg.targets?.length ? ` · selected targets: ${msg.targets.join(', ')}` : '';
      const rawHighlights = msg.rawHighlights?.length
        ? ` · raw samples: ${msg.rawHighlights.join(', ')}`
        : '';
      const rejected = msg.rejectedPair?.length
        ? ` · rejected by board model: ${msg.rejectedPair.join(' / ')}`
        : '';
      const candidates = (msg.candidates || []).map(candidate =>
        `${candidate.square} RGB(${candidate.rgb.join(',')}) Δ${candidate.lightDistance}/${candidate.darkDistance}`
      ).join(' · ');
      const diagnostic =
        `${msg.orientation} · highlights: ${highlights}${rawHighlights}${targets}${rejected}` +
        (candidates ? ` · closest highlight samples: ${candidates}` : '');
      if (elDbgMoveScan) elDbgMoveScan.textContent = diagnostic;
      if (Date.now() - lastMoveScanLogTime >= 2000) {
        log(`Pixel scanner: ${diagnostic}`, 'debug');
        lastMoveScanLogTime = Date.now();
      }
      break;
    }

    case 'frame_preview':
      showPreview(msg.jpegBase64, msg.frame);
      break;

    case 'state_change':
      setAppState(msg.state);
      log(`State → ${msg.state}: ${msg.reason}`, msg.state === 'ERROR' ? 'error' : 'info');
      break;

    case 'error':
      if (msg.commandId === pendingSquarePaletteCommandId) {
        pendingSquarePaletteCommandId = '';
        lastAppliedSquarePalette = '';
        const status = document.getElementById('square-color-status');
        if (status) status.textContent = `Could not apply "${selectedSquareTheme}": ${msg.message}`;
      }
      showError(msg.message);
      log(`[${msg.code}] ${msg.message}${msg.detail ? ' – ' + msg.detail : ''}`, 'error');
      break;

    case 'ack':
      if (msg.commandId === pendingSquarePaletteCommandId) {
        pendingSquarePaletteCommandId = '';
        const status = document.getElementById('square-color-status');
        if (status) status.textContent = `Active theme: "${selectedSquareTheme}" — palette applied to move detection.`;
        break;
      }
      log(`Ack: ${msg.commandId}`, 'debug');
      break;

    case 'snapshot_saved':
      log(`Snapshot saved → ${msg.path}`, 'ok');
      break;

    case 'board_candidates':
      handleBoardCandidates(msg.candidates);
      break;

    case 'board_locked':
      handleBoardLocked(msg);
      break;

    case 'board_unlocked':
      handleBoardUnlocked();
      break;

    case 'square_occupancy':
      currentOccupancy = msg.squares || {};
      if (elDbgOccupancy && msg.summary) {
        elDbgOccupancy.textContent = `${msg.summary.occupied} Occupied · ${msg.summary.empty} Empty (${msg.summary.stable} stable)`;
      }
      renderOccupancyGrid(currentOccupancy);
      break;

    case 'move_decision':
      if (elDbgChanges) {
        const capture = msg.isCapture ? ` capture on ${msg.capturedSquare}` : '';
        elDbgChanges.textContent = `${msg.kind}: ${msg.sourceSquare} → ${msg.destinationSquare}${capture} (${Math.round(msg.confidence * 100)}%, ${msg.source})`;
      }
      log(`Move verified: ${msg.sourceSquare} → ${msg.destinationSquare}${msg.isCapture ? ' (capture)' : ''}`, 'ok');
      break;

    case 'capture_event':
      if (elDbgCaptureEvent) elDbgCaptureEvent.textContent = `${msg.sourceSquare} → ${msg.destinationSquare} · ${Math.round(msg.confidence * 100)}%`;
      log(`Capture event emitted: ${msg.sourceSquare} → ${msg.capturedSquare}`, 'ok');
      break;

    case 'board_debug':
      // The click-through overlay owns live board diagnostics.
      break;

    case 'square_scan_status':
      // Consumed by the click-through overlay; no control-panel action needed.
      break;

    default:
      log(`Unknown message type: ${msg.type}`, 'warn');
  }
}

function updateEffectsControls() {
  elBtnStart.disabled = effectsActive;
  elBtnStop.disabled = !effectsActive;
  elBtnStart.textContent = effectsActive ? '▶ Active' : '▶ Start';
}

function setEffectsActive(active) {
  effectsActive = Boolean(active);
  elPythonStatus.className = `status-indicator ${effectsActive ? 'online' : 'offline'}`;
  elPythonLabel.textContent = effectsActive ? 'Active' : 'Inactive';
  updateEffectsControls();
}

function handleBoardCandidates(candidates) {
  currentCandidates = candidates || [];
  elCandidateSelect.innerHTML = '';

  if (currentCandidates.length > 0) {
    elCandidateGroup.classList.remove('hidden');
    currentCandidates.forEach((c) => {
      const opt = document.createElement('option');
      opt.value = c.id.toString();
      opt.textContent = `Candidate #${c.id + 1} (${Math.round(c.score * 100)}% match, ${c.rect.width}×${c.rect.height})`;
      elCandidateSelect.appendChild(opt);
    });

    selectedCandidate = currentCandidates[0];
    elCalX.value = selectedCandidate.rect.left.toString();
    elCalY.value = selectedCandidate.rect.top.toString();
    elCalW.value = selectedCandidate.rect.width.toString();
    elCalH.value = selectedCandidate.rect.height.toString();

    elBtnLockBoard.disabled = false;
    log(`Auto-detect found ${currentCandidates.length} candidate(s). Best match: ${Math.round(selectedCandidate.score * 100)}%`, 'ok');
  } else {
    elCandidateGroup.classList.add('hidden');
    selectedCandidate = null;
    log('No chessboard candidate detected on screen', 'warn');
  }
}

function handleBoardLocked(msg) {
  lockedBoard = msg;
  if (msg.orientation === 'white_bottom' || msg.orientation === 'black_bottom') {
    currentOrientation = msg.orientation;
  }
  selectedCandidate = null;

  elBoardSummary.textContent = `${msg.rect.width}×${msg.rect.height} at (${msg.rect.left}, ${msg.rect.top}) · 64 squares locked`;
  elBoardStatusBadge.textContent = 'LOCKED';
  elBoardStatusBadge.className = 'badge badge-confirmed';

  elBtnLockBoard.textContent = '🔓 Unlock Board';
  elBtnLockBoard.className = 'btn btn-danger';
  elBtnLockBoard.disabled = false;
  elBtnStartPosition.disabled = false;

  elCandidateGroup.classList.add('hidden');
  log(`Board locked at (${msg.rect.left}, ${msg.rect.top}) ${msg.rect.width}×${msg.rect.height} [${msg.orientation}]`, 'ok');
}

function handleBoardUnlocked() {
  lockedBoard = null;
  selectedCandidate = null;

  elBoardSummary.textContent = 'No board locked yet';
  elBoardStatusBadge.textContent = 'NO BOARD';
  elBoardStatusBadge.className = 'badge badge-idle';

  elBtnLockBoard.textContent = '🔒 Lock Board';
  elBtnLockBoard.className = 'btn btn-secondary';
  elBtnLockBoard.disabled = currentCandidates.length === 0;
  elBtnStartPosition.disabled = true;

  log('Board unlocked', 'info');
}

// ─── Capture controls ─────────────────────────────────────────────────────────
function startCapture() {
  const monitorIndex = parseInt(elMonitorSelect.value, 10);
  const fps = Math.max(1, Math.min(30, parseInt(elFpsInput.value, 10) || 5));
  const sendPreviews = false;

  currentMonitorIndex = monitorIndex;
  if (statMonitor) statMonitor.textContent = `Monitor ${monitorIndex}`;

  window.cvfx.setEffectsActive(true);
  setEffectsActive(true);

  if (!captureRunning) {
    window.cvfx.sendCommand({
      type: 'start_capture',
      commandId: `start-${Date.now()}`,
      monitorIndex,
      fps,
      sendPreviews,
    });
    captureRunning = true;
    log(`Started capture on monitor ${monitorIndex} @ ${fps} fps`, 'ok');
  } else {
    log('Effects activated for the current board.', 'ok');
  }
}

function stopCapture() {
  window.cvfx.setEffectsActive(false);
  setEffectsActive(false);
  window.cvfx.sendCommand({
    type: 'stop_capture',
    commandId: `stop-${Date.now()}`,
  });

  captureRunning = false;
  updateEffectsControls();
  elPreviewCanvas.style.display = 'none';
  elPreviewPh.style.display = '';
  elPreviewStats.textContent = '–';
  log('Capture stopped', 'info');
}

// ─── Event listeners ──────────────────────────────────────────────────────────
elBtnStart.addEventListener('click', startCapture);
elBtnStop.addEventListener('click',  stopCapture);

elBtnRefresh.addEventListener('click', () => {
  window.cvfx.sendCommand({ type: 'get_monitors', commandId: `mon-${Date.now()}` });
  log('Refreshing monitor list…', 'info');
});

elMonitorSelect.addEventListener('change', () => {
  currentMonitorIndex = parseInt(elMonitorSelect.value, 10);
  if (captureRunning) {
    stopCapture();
    setTimeout(startCapture, 200);
  }
});

elDebugToggle.addEventListener('change', () => {
  const enabled = elDebugToggle.checked;
  window.cvfx.sendCommand({ type: 'set_debug_mode', commandId: `dbg-${Date.now()}`, enabled });
  log(`Debug mode ${enabled ? 'enabled' : 'disabled'}`, 'info');
});

elFpsInput.addEventListener('change', () => {
  if (!captureRunning) return;
  const fps = Math.max(1, Math.min(30, parseInt(elFpsInput.value, 10) || 5));
  window.cvfx.sendCommand({ type: 'set_fps', commandId: `fps-${Date.now()}`, fps });
  log(`FPS target set to ${fps}`, 'info');
});

elBtnClearLog.addEventListener('click', () => {
  elLogList.innerHTML = '';
  logCount = 0;
});

// Phase 2: Board detection & tracking UI controls
elBtnAutoDetect.addEventListener('click', () => {
  log('Scanning for chessboard candidates…', 'info');
  window.cvfx.sendCommand({ type: 'detect_board', commandId: `detect-${Date.now()}` });
});

elCandidateSelect.addEventListener('change', () => {
  const cid = parseInt(elCandidateSelect.value, 10);
  selectedCandidate = currentCandidates.find((c) => c.id === cid) || null;
  if (selectedCandidate) {
    elCalX.value = selectedCandidate.rect.left.toString();
    elCalY.value = selectedCandidate.rect.top.toString();
    elCalW.value = selectedCandidate.rect.width.toString();
    elCalH.value = selectedCandidate.rect.height.toString();
    window.cvfx.sendCommand({
      type: 'select_candidate',
      commandId: `sel-${Date.now()}`,
      candidateId: cid,
    });
    log(`Selected candidate #${cid + 1} (${selectedCandidate.rect.width}×${selectedCandidate.rect.height})`, 'info');
  }
});

elBtnManualCal.addEventListener('click', () => {
  elManualCalInputs.classList.toggle('hidden');
});

elBtnApplyManualCal.addEventListener('click', () => {
  const left = parseInt(elCalX.value, 10) || 0;
  const top = parseInt(elCalY.value, 10) || 0;
  const width = parseInt(elCalW.value, 10) || 400;
  const height = parseInt(elCalH.value, 10) || 400;

  window.cvfx.sendCommand({
    type: 'set_manual_board',
    commandId: `man-${Date.now()}`,
    left,
    top,
    width,
    height,
    orientation: currentOrientation,
  });
  log(`Manual calibration applied: ${width}×${height} at (${left}, ${top})`, 'ok');
});

elBtnLockBoard.addEventListener('click', () => {
  if (lockedBoard) {
    window.cvfx.sendCommand({ type: 'unlock_board', commandId: `unlk-${Date.now()}` });
  } else if (selectedCandidate) {
    window.cvfx.sendCommand({
      type: 'select_candidate',
      commandId: `sel-${Date.now()}`,
      candidateId: selectedCandidate.id,
    });
  } else {
    const left = parseInt(elCalX.value, 10) || 0;
    const top = parseInt(elCalY.value, 10) || 0;
    const width = parseInt(elCalW.value, 10) || 400;
    const height = parseInt(elCalH.value, 10) || 400;
    window.cvfx.sendCommand({
      type: 'set_manual_board',
      commandId: `lock-${Date.now()}`,
      left,
      top,
      width,
      height,
      orientation: currentOrientation,
    });
  }
});

elBtnToggleOrientation.addEventListener('click', () => {
  currentOrientation = currentOrientation === 'white_bottom' ? 'black_bottom' : 'white_bottom';
  elBtnToggleOrientation.textContent = 'Flip';
  window.cvfx.sendCommand({
    type: 'set_orientation',
    commandId: `ori-${Date.now()}`,
    orientation: currentOrientation,
  });
  log(`Board orientation set to: ${currentOrientation.replace('_', ' ')}`, 'info');
});

elBtnStartPosition.addEventListener('click', () => {
  window.cvfx.sendCommand({ type: 'reset_game', commandId: `reset-${Date.now()}` });
  log('Finding and locking the board, then rebuilding the 16 + 16 opening state.', 'ok');
});

elDeathEffectsToggle.addEventListener('change', async () => {
  const active = await window.cvfx.setDeathEffectsActive(elDeathEffectsToggle.checked);
  elDeathEffectsToggle.checked = active;
});

document.getElementById('square-theme-select').addEventListener('change', event => {
  selectedSquareTheme = event.currentTarget.value;
  renderSquareTheme();
  saveSquareThemes();
  applySquarePalette();
});
document.getElementById('btn-new-square-theme').addEventListener('click', () => {
  const nameInput = /** @type {HTMLInputElement} */ (document.getElementById('square-theme-name'));
  const name = nameInput.value.trim();
  const status = document.getElementById('square-color-status');
  if (!name) {
    status.textContent = 'Enter a name for the new theme.';
    nameInput.focus();
    return;
  }
  if (squareThemes.some(theme => theme.name.toLowerCase() === name.toLowerCase())) {
    status.textContent = 'A theme with that name already exists.';
    nameInput.focus();
    nameInput.select();
    return;
  }
  squareThemes.push({ name, builtIn: false, colors: { ...activeSquareTheme().colors } });
  selectedSquareTheme = name;
  nameInput.value = '';
  renderSquareTheme();
  saveSquareThemes();
  applySquarePalette();
  status.textContent = `Created "${name}" from the previous theme.`;
});
document.getElementById('square-theme-name').addEventListener('keydown', event => {
  if (event.key === 'Enter') {
    event.preventDefault();
    document.getElementById('btn-new-square-theme').click();
  }
});
document.getElementById('btn-delete-square-theme').addEventListener('click', () => {
  const theme = activeSquareTheme();
  if (theme.builtIn) return;
  squareThemes = squareThemes.filter(item => item !== theme);
  selectedSquareTheme = 'Chess.com Pink';
  renderSquareTheme();
  saveSquareThemes();
  applySquarePalette();
});
document.getElementById('square-color-list').addEventListener('input', event => {
  if (event.target.matches('.square-color-input')) updateSquareThemeColor(event.target);
});
document.getElementById('btn-import-square-colors').addEventListener('click', () => {
  const status = document.getElementById('square-color-status');
  try {
    const parsed = JSON.parse(document.getElementById('square-color-json').value);
    activeSquareTheme().colors = validateSquarePalette(parsed);
    renderSquareTheme();
    saveSquareThemes();
    applySquarePalette();
    status.textContent = `Imported all ${SQUARE_COLOR_KEYS.length} colors into "${selectedSquareTheme}".`;
  } catch (error) {
    status.textContent = `Could not import colors: ${error.message}`;
  }
});
document.addEventListener('keydown', event => {
  if (!event.ctrlKey || !event.altKey || !/^[0-9]$/.test(event.key)) return;
  const index = event.key === '0' ? 9 : Number(event.key) - 1;
  if (index < 0 || index >= SQUARE_COLOR_KEYS.length) return;
  event.preventDefault();
  pickSquareColor(SQUARE_COLOR_KEYS[index]);
});

// Particle editor is deliberately immediate: each edit is sent to the overlay
// after a tiny debounce, and persisted locally for the next launch.
fxInputIds.forEach(id => fx(id).addEventListener('input', saveFxLive));
fx('fx-movement-duration').addEventListener('input', saveFxLive);
fx('fx-shape').addEventListener('change', () => { updateImageFieldVisibility(); saveFxLive(); });
fx('fx-source-image').addEventListener('change', saveFxLive);
fx('fx-directional').addEventListener('change', saveFxLive);
// Direct typing replaces the old value; native spinner arrows retain their
// normal increment/decrement behavior on the selected numeric value.
document.querySelectorAll('input[type="number"]').forEach(input => input.addEventListener('focus', () => input.select()));
window.addEventListener('beforeunload', flushFxSave);
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') flushFxSave(); });
new ResizeObserver(() => drawFxGraph()).observe(document.getElementById('fx-graph'));
document.querySelectorAll('.graph-mode').forEach(button => button.addEventListener('click', () => {
  selectedGraph = button.dataset.graph; selectedNode = null;
  document.querySelectorAll('.graph-mode').forEach(item => item.classList.toggle('active', item === button));
  drawFxGraph();
}));
fx('fx-emission').addEventListener('change', () => {
  const emission = currentEmission(), name = fx('fx-emission').value.trim();
  emission.name = name || `Emission ${selectedEmission + 1}`; writeFxControls(); saveFxLive();
});
fx('fx-function').addEventListener('change', () => {
  const oldName = fxConfig.selectedFunction, entered = fx('fx-function').value.trim();
  const name = entered.endsWith('.json') ? entered : `${entered}.fx.json`;
  if (!entered || (name !== oldName && fxConfig.functions[name])) { writeFxControls(); return; }
  fxConfig.functions[name] = fxConfig.functions[oldName];
  if (name !== oldName) delete fxConfig.functions[oldName];
  if (name !== oldName) replacePieceEffectReference(oldName, name);
  fxConfig.selectedFunction = name; writeFxControls(); saveFxLive();
});
document.getElementById('btn-new-function').addEventListener('click', () => {
  readFxControls();
  let number = 2, name = `effect-${number}.fx.json`;
  while (fxConfig.functions[name]) name = `effect-${++number}.fx.json`;
  fxConfig.functions[name] = { emissions: [JSON.parse(JSON.stringify(EMISSION_DEFAULT))] };
  fxConfig.selectedFunction = name; selectedEmission = 0; deleteFunctionArmed = false;
  writeFxControls(); saveFxLive();
});
document.getElementById('btn-delete-function').addEventListener('click', () => {
  const names = Object.keys(fxConfig.functions);
  if (names.length <= 1) return;
  if (!deleteFunctionArmed) {
    deleteFunctionArmed = true;
    refreshFxSelectors();
    return;
  }
  const deleted = fxConfig.selectedFunction;
  delete fxConfig.functions[deleted];
  fxConfig.selectedFunction = Object.keys(fxConfig.functions)[0];
  replacePieceEffectReference(deleted, fxConfig.selectedFunction);
  selectedEmission = 0; selectedNode = null; deleteFunctionArmed = false;
  writeFxControls(); saveFxLive();
});
document.getElementById('btn-add-emission').addEventListener('click', () => {
  readFxControls();
  currentFunction().emissions.push(JSON.parse(JSON.stringify(EMISSION_DEFAULT)));
  selectedEmission = currentFunction().emissions.length - 1;
  writeFxControls(); saveFxLive();
});
document.getElementById('btn-copy-emission')?.addEventListener('click', () => {
  copyEmissionToClipboard(selectedEmission);
});
document.getElementById('btn-paste-emission')?.addEventListener('click', pasteEmission);
document.getElementById('btn-copy-function')?.addEventListener('click', copyFunction);
document.getElementById('btn-delete-emission').addEventListener('click', () => {
  const emissions = currentFunction().emissions;
  if (emissions.length <= 1) return;
  emissions.splice(selectedEmission, 1); selectedEmission = Math.max(0, selectedEmission - 1);
  writeFxControls(); saveFxLive();
});
document.getElementById('btn-select-fx-image').addEventListener('click', async () => {
  const fileUrl = await window.cvfx.selectEffectImage();
  if (!fileUrl) return;
  fx('fx-image').value = fileUrl;
  fx('fx-source-image').checked = false;
  // Choosing an asset should visibly use it without an extra shape-setting step.
  if (fx('fx-shape').value !== 'flipbook') fx('fx-shape').value = 'image';
  saveFxLive();
});
document.getElementById('btn-test-fx').addEventListener('click', async () => {
  await saveFxLive(true);
  // The preview is the actual transparent overlay moved to this black box;
  // it therefore exercises the same emitter used by capture events.
  const box = document.getElementById('fx-preview-box').getBoundingClientRect();
  await window.cvfx.testEffectPreview({ left: box.left, top: box.top, width: box.width, height: box.height });
});
document.getElementById('btn-sync-github').addEventListener('click', async () => {
  const status = document.getElementById('square-color-status');
  const saved = await window.cvfx.saveProjectSettings({ squareThemes: { selected: selectedSquareTheme, themes: squareThemes }, fxConfig });
  if (!saved.ok) {
    if (status) status.textContent = `GitHub save failed: ${saved.message}`;
    return;
  }
  const result = await window.cvfx.syncProjectDataToGitHub();
  if (status) status.textContent = result.message || 'Saved settings synced to GitHub.';
  if (!result.ok) {
    console.error('GitHub sync failed:', result.message);
  }
});

// ─── Boot ─────────────────────────────────────────────────────────────────────
async function init() {
  log('Chess Vision FX starting…', 'info');
  setAppState('NO_BOARD');
  setPythonOnline(false);
  await loadSquareThemes();

  // Subscribe to Python events
  window.cvfx.onPythonReady(() => {
    setPythonOnline(true);
  });

  window.cvfx.onPythonMessage(handlePythonMessage);

  window.cvfx.onPythonStderr((line) => {
    log(`[py] ${line}`, 'debug');
  });

  window.cvfx.onMainMessage('effects-active', (active) => {
    setEffectsActive(active);
    log(`Effects ${active ? 'activated' : 'deactivated'}.`, 'info');
  });

  window.cvfx.onMainMessage('death-effects-active', (active) => {
    elDeathEffectsToggle.checked = Boolean(active);
  });

  setEffectsActive(await window.cvfx.getEffectsActive());
  elDeathEffectsToggle.checked = await window.cvfx.getDeathEffectsActive();

  const projectSettings = await window.cvfx.loadProjectSettings();
  const storedFx = projectSettings.fxConfig || localStorage.getItem(FX_CONFIG_KEY);
  const backupFx = localStorage.getItem(FX_CONFIG_BACKUP_KEY);
  const mainFx = await window.cvfx.getEffectConfig();
  const savedConfigs = [
    ['project data', projectSettings.fxConfig],
    ['local storage', localStorage.getItem(FX_CONFIG_KEY)],
    ['backup storage', backupFx],
    ['main process', mainFx],
  ];
  let savedConfigFound = false;
  for (const [source, candidate] of savedConfigs) {
    if (!candidate) continue;
    try {
      const parsed = typeof candidate === 'string' ? JSON.parse(candidate) : candidate;
      const migrated = migrateFxConfig(parsed);
      if (!isValidFxConfig(migrated)) throw new Error('Config has no saved effect functions.');
      fxConfig = migrated;
      fxConfigReady = true;
      savedConfigFound = true;
      if (source !== 'local storage') {
        console.warn(`Loaded particle effects from ${source}; the primary saved config was unavailable.`);
      }
      break;
    } catch (error) {
      console.error(`Could not load particle effects from ${source}:`, error);
    }
  }
  if (!savedConfigFound) {
    const hasInvalidSavedConfig = Boolean(storedFx || backupFx || mainFx);
    fxConfig = migrateFxConfig(JSON.parse(JSON.stringify(FX_DEFAULT)));
    fxConfigReady = !hasInvalidSavedConfig;
    if (hasInvalidSavedConfig) {
      console.error('Saved particle effects could not be loaded. Defaults are shown, and saving is blocked to protect the stored config.');
    }
  }
  // The editor is a work surface, so use the unused center column rather than
  // competing with capture and board controls in the compact sidebar.
  document.getElementById('content').prepend(document.getElementById('panel-fx'));
  writeFxControls();
  // Establish the initial configuration for the overlay, including first run.
  if (fxConfigReady) window.cvfx.setEffectConfig(fxConfig);

  // Load displays from Electron
  try {
    const displays = await window.cvfx.getDisplays();
    log(`Electron sees ${displays.length} display(s)`, 'info');
    displays.forEach((d) => {
      log(`  Display ${d.index}: ${d.bounds.width}×${d.bounds.height} @ (${d.bounds.x},${d.bounds.y}) scale=${d.scaleFactor}${d.isPrimary?' [primary]':''}`, 'debug');
    });
  } catch (err) {
    log(`Failed to get displays: ${err}`, 'warn');
  }

  log('Ready. Select a monitor and click Start.', 'ok');
}

init();
