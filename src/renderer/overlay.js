const labels = document.getElementById('square-labels');
const thinking = document.getElementById('thinking');
const action = document.getElementById('action');
const counts = document.getElementById('counts');
const output = document.getElementById('output');
const boardContainer = document.getElementById('board-container');
const fxContainer = document.getElementById('fx-container');

let board = null;
let realtimeOccupied = {};
let trackedTeams = {};
let squareScanStatus = {};
let lastCaptureTimestamp = 0;
let lastCapturedSquare = '';
let effectsActive = false;
let deathEffectsActive = true;
let localTeam = 'WHITE';
let previewModeTimer = null;
const PIECE_TYPES = ['pawn', 'queen', 'rook', 'bishop', 'king', 'knight'];
const PIECE_NOTATION = { pawn: 'P', knight: 'N', bishop: 'B', rook: 'R', queen: 'Q', king: 'K' };
let pieceTypes = {};
let initializePieceTypesOnBoardUpdate = false;

// Overlay debug labels/HUD are OFF by default. F toggles only this display;
// capture effects are governed independently by effectsActive.
let labelsVisible = false;

// Show/hide the output HUD (thinking/action/counts) and labels together
function setLabelsVisible(visible) {
  labelsVisible = visible;
  if (output) output.style.display = visible ? '' : 'none';
  draw();
}

// ─── Reusable particle emitter ────────────────────────────────────────────────
// The effect functions below only compose calls to emit(); they contain no
// rendering logic and can later be selected per chess piece without changes here.
const DEFAULT_FX = {
  count: 5, zIndex: 0, position: { x: 0, y: 0 }, speed: [70, 190], rotation: [0, 360],
  direction: [-180, 180], directional: false, acceleration: 0, drag: 0, rotationSpeed: [-180, 180], lifetime: [0.45, 0.9],
  shape: 'star', imageId: '', flipbook: { size: 2 },
  glow: 0, imageColorMode: 'tint',
  size: [{ t: 0, v: 50 }, { t: 1, v: 50 }],
  transparency: [{ t: 0, v: 0 }, { t: 1, v: 1 }],
  color: [{ t: 0, v: '#fff4b0' }, { t: 1, v: '#d946ef' }]
};
let effectConfig = { selectedFunction: 'default-capture.fx.json', functions: {
  'default-capture.fx.json': { emissions: [structuredClone(DEFAULT_FX)] }
}};
const particles = [];
const particlePool = [];
const trailTimers = new Set();
const MAX_ACTIVE_PARTICLES = 600;
const MAX_POOLED_PARTICLES = 600;
const PARTICLE_BASELINE_PX = 100;
const range = ([min, max]) => Number(min) + Math.random() * (Number(max) - Number(min));
const lerp = (a, b, t) => a + (b - a) * t;
function movementDegreesFromSquares(source, destination) {
  if (!source || !destination) return 0;
  const sourceFile = source.charCodeAt(0) - 97;
  const sourceRow = 8 - Number(source[1]);
  const destinationFile = destination.charCodeAt(0) - 97;
  const destinationRow = 8 - Number(destination[1]);
  const dx = destinationFile - sourceFile;
  const dy = destinationRow - sourceRow;
  if (dx === 0 && dy === 0) return 0;
  const radians = Math.atan2(dx, -dy);
  return (radians * 180 / Math.PI + 360) % 360;
}
function graphValue(points, t) {
  if (!Array.isArray(points) || points.length === 0) return 0;
  if (t <= points[0].t) return Number(points[0].v) || 0;
  for (let i = 1; i < points.length; i++) if (t <= points[i].t) {
    const a = points[i - 1], b = points[i];
    const span = Number(b.t) - Number(a.t);
    if (span <= 0.000001) return Number(b.v) || 0;
    return lerp(Number(a.v), Number(b.v), (t - a.t) / span);
  }
  return Number(points[points.length - 1].v) || 0;
}
/** Per-particle size: each node has v=[min,max]; rand is fixed per particle (0..1). */
function sizeValue(points, t, rand) {
  if (!Array.isArray(points) || points.length === 0) return 0;
  const nodeVal = n => {
    if (Array.isArray(n.v)) return n.v[0] + rand * (n.v[1] - n.v[0]);
    return Number(n.v) || 0;
  };
  if (t <= points[0].t) return nodeVal(points[0]);
  for (let i = 1; i < points.length; i++) if (t <= points[i].t) {
    const a = points[i - 1], b = points[i];
    const span = Number(b.t) - Number(a.t);
    if (span <= 0.000001) return nodeVal(b);
    return lerp(nodeVal(a), nodeVal(b), (t - a.t) / span);
  }
  return nodeVal(points[points.length - 1]);
}
function hexToRgb(hex) {
  const value = String(hex).replace('#', '');
  const n = parseInt(value.length === 3 ? value.split('').map(c => c + c).join('') : value, 16);
  return [n >> 16 & 255, n >> 8 & 255, n & 255];
}
function colorValue(points, t) {
  if (!Array.isArray(points) || points.length === 0) return 'rgb(255, 255, 255)';
  let a = points[0], b = points[points.length - 1];
  for (let i = 1; i < points.length; i++) if (t <= points[i].t) { a = points[i - 1]; b = points[i]; break; }
  const asRgb = value => Array.isArray(value) ? value : hexToRgb(value);
  const m = a === b ? 0 : (t - a.t) / (b.t - a.t), x = asRgb(a.v), y = asRgb(b.v);
  return `rgb(${Math.round(lerp(x[0],y[0],m))}, ${Math.round(lerp(x[1],y[1],m))}, ${Math.round(lerp(x[2],y[2],m))})`;
}
function validCurve(points, fallback) {
  if (!Array.isArray(points) || points.length === 0) return fallback;
  const curve = [];
  points.filter(point => point && Number.isFinite(Number(point.t))).sort((a, b) => Number(a.t) - Number(b.t)).forEach(point => {
    const last = curve[curve.length - 1];
    if (last && Math.abs(Number(last.t) - Number(point.t)) < 0.00001) curve[curve.length - 1] = point;
    else curve.push(point);
  });
  return curve.length ? curve : fallback;
}
function imageSource(imageId) {
  const id = String(imageId || '').trim();
  // A bare number or rbxassetid:// value is convenient when reusing Roblox art.
  const robloxId = id.match(/^(?:rbxassetid:\/\/)?(\d+)$/)?.[1];
  return robloxId ? `https://assetdelivery.roblox.com/v1/asset/?id=${robloxId}` : id;
}
function acquireParticle(shape) {
  const el = particlePool.pop() || document.createElement('div');
  el.className = `fx-particle shape-${shape || 'circle'}`;
  // Images are drawn into this invisible baseline square and then scaled by
  // the Size graph, so source-image dimensions never determine particle size.
  el.style.cssText = `width:${PARTICLE_BASELINE_PX}px;height:${PARTICLE_BASELINE_PX}px`;
  return el;
}
function acquireGlowParticle() {
  const el = particlePool.pop() || document.createElement('div');
  el.className = 'fx-particle fx-image-glow';
  el.style.cssText = `width:${PARTICLE_BASELINE_PX}px;height:${PARTICLE_BASELINE_PX}px`;
  return el;
}
function releaseParticle(particle) {
  const { el } = particle;
  el.remove();
  el.style.cssText = '';
  el.className = 'fx-particle';
  if (particlePool.length < MAX_POOLED_PARTICLES) particlePool.push(el);
  if (particle.glowEl) {
    particle.glowEl.remove();
    particle.glowEl.style.cssText = '';
    particle.glowEl.className = 'fx-particle';
    if (particlePool.length < MAX_POOLED_PARTICLES) particlePool.push(particle.glowEl);
  }
}
/** The one reusable emitter. Every capture effect calls this with settings. */
function emit(settings, square, directionDegrees = 0) {
  if (!fxContainer || !square) return;
  const baseX = ((square.col + 0.5 + Number(settings.position?.x || 0)) / 8) * fxContainer.clientWidth;
  const baseY = ((square.row + 0.5 + Number(settings.position?.y || 0)) / 8) * fxContainer.clientHeight;
  const count = Math.min(Math.max(0, Number(settings.count || 0)), Math.max(0, MAX_ACTIVE_PARTICLES - particles.length));
  const directionalOffset = settings.directional && Number.isFinite(Number(directionDegrees)) ? Number(directionDegrees) : 0;
  const curves = {
    size: validCurve(settings.size, DEFAULT_FX.size),
    transparency: validCurve(settings.transparency, DEFAULT_FX.transparency),
    color: validCurve(settings.color, DEFAULT_FX.color),
  };
  const source = imageSource(settings.imageId), imageShape = settings.shape === 'image' || settings.shape === 'flipbook';
  const tintImage = imageShape && settings.imageColorMode !== 'source' && Boolean(source);
  for (let i = 0; i < count; i++) {
    const angle = range(settings.direction) * Math.PI / 180, speed = range(settings.speed);
    const acceleration = Number(settings.acceleration || 0) + Number(settings.drag || 0);
    const el = acquireParticle(settings.shape);
    let glowEl = null;
    if (imageShape && source) {
      const imageUrl = `url("${source}")`;
      if (tintImage) {
        // Chromium recognizes the prefixed shorthand most consistently for
        // local PNGs; explicit longhands keep flipbook updates independent.
        el.style.mask = `${imageUrl} center / cover no-repeat`;
        el.style.webkitMask = `${imageUrl} center / cover no-repeat`;
        el.style.maskImage = imageUrl; el.style.webkitMaskImage = imageUrl;
        el.style.maskRepeat = 'no-repeat'; el.style.webkitMaskRepeat = 'no-repeat';
        el.style.maskMode = 'alpha'; el.style.webkitMaskPosition = 'center'; el.style.maskPosition = 'center';
        el.style.maskSize = 'cover'; el.style.webkitMaskSize = 'cover';
        // Chromium clips filters applied to a CSS-masked element. Use the
        // image's alpha-bearing source below it so its drop-shadow can extend
        // past the image edge.
        if (Number(settings.glow) > 0) {
          glowEl = acquireGlowParticle();
          // Keep the source visible (normally white for particle assets).
          // The previous brightness(0) conversion made this duplicate black,
          // which was visible as a dark outline under anti-aliased edges.
          glowEl.style.backgroundImage = imageUrl;
          glowEl.style.backgroundRepeat = 'no-repeat';
          glowEl.style.backgroundPosition = 'center';
          glowEl.style.backgroundSize = 'cover';
          fxContainer.appendChild(glowEl);
        }
      } else {
        el.style.backgroundImage = imageUrl;
        el.style.backgroundRepeat = 'no-repeat';
        el.style.backgroundPosition = 'center';
        el.style.backgroundSize = 'cover';
      }
      if (settings.shape === 'flipbook') {
        const gridSize = Math.max(2, Math.min(16, Math.round(Number(settings.flipbook?.size) || 2)));
        const spriteSize = `${gridSize * 100}% ${gridSize * 100}%`;
        if (tintImage) {
          el.style.maskRepeat = 'no-repeat'; el.style.webkitMaskRepeat = 'no-repeat';
          el.style.maskSize = spriteSize; el.style.webkitMaskSize = spriteSize;
          el.style.maskPosition = '0% 0%'; el.style.webkitMaskPosition = '0% 0%';
        } else {
          el.style.backgroundSize = spriteSize;
          el.style.backgroundPosition = '0% 0%';
        }
        if (glowEl) {
          glowEl.style.backgroundSize = spriteSize;
          glowEl.style.backgroundPosition = '0% 0%';
        }
      }
    }
    fxContainer.appendChild(el);
    // Apply emission z-index so higher-indexed emissions render on top.
    const zIdx = String(Math.round(Number(settings.zIndex || 0)));
    el.style.zIndex = zIdx;
    const sizeRand = Math.random(); // fixed per-particle for consistent size variance
    const rotation = range(settings.rotation) + directionalOffset;
    // 0° points upward; clockwise angles put 90° to the right.
    particles.push({ el, x: baseX, y: baseY, vx: Math.sin(angle)*speed, vy: -Math.cos(angle)*speed,
      ax: Math.sin(angle)*acceleration, ay: -Math.cos(angle)*acceleration,
      rotation, rotationSpeed: range(settings.rotationSpeed), born: performance.now(),
      life: range(settings.lifetime)*1000, settings, curves, tintImage, glowEl, sizeRand });
    if (glowEl) glowEl.style.zIndex = zIdx;
  }
}
function updateParticles(now) {
  try {
    for (let i = particles.length - 1; i >= 0; i--) {
      const p = particles[i], age = now - p.born, t = Math.min(1, age / p.life);
      if (t >= 1) {
        releaseParticle(p);
        const last = particles.pop();
        if (i < particles.length) particles[i] = last;
        continue;
      }
      const seconds = age / 1000, size = Math.max(0, sizeValue(p.curves.size, t, p.sizeRand ?? 0.5));
      const rawTrans = Number(graphValue(p.curves.transparency, t));
      const transVal = Number.isFinite(rawTrans) ? (rawTrans > 1 ? rawTrans / 100 : rawTrans) : 0;
      const alpha = Math.max(0, Math.min(1, 1 - transVal));
      const color = colorValue(p.curves.color, t);
      p.el.style.backgroundColor = color; p.el.style.opacity = String(alpha);
      const glow = Math.max(0, Number(p.settings.glow) || 0);
      p.el.style.filter = p.tintImage ? '' : (glow > 0 ? `drop-shadow(0 0 ${glow}px ${color}) drop-shadow(0 0 ${Math.max(1, glow / 2)}px ${color})` : '');
      // Clamp time so drag can never reverse the particle: stop at the moment speed hits zero.
      const speed0 = Math.sqrt(p.vx * p.vx + p.vy * p.vy);
      const accSq = p.ax * p.ax + p.ay * p.ay;
      const dragging = accSq > 0 && (p.ax * p.vx + p.ay * p.vy) < 0;
      const tEff = dragging ? Math.min(seconds, speed0 / Math.sqrt(accSq)) : seconds;
      const x = p.x + p.vx*tEff + .5*p.ax*tEff*tEff - PARTICLE_BASELINE_PX / 2;
      const y = p.y + p.vy*tEff + .5*p.ay*tEff*tEff - PARTICLE_BASELINE_PX / 2;
      p.el.style.transform = `translate3d(${x}px, ${y}px, 0) rotate(${p.rotation + p.rotationSpeed*seconds}deg) scale(${size / PARTICLE_BASELINE_PX})`;
      if (p.glowEl) {
        // The alpha-bearing white source remains visible beneath the tinted
        // foreground; its shadow is the configured color and can expand
        // outside the image bounds.
        p.glowEl.style.opacity = String(alpha);
        p.glowEl.style.filter = `drop-shadow(0 0 ${glow}px ${color}) drop-shadow(0 0 ${Math.max(1, glow / 2)}px ${color})`;
        p.glowEl.style.transform = p.el.style.transform;
      }
      if (p.settings.shape === 'flipbook') {
        const gridSize = Math.max(2, Math.min(16, Math.round(Number(p.settings.flipbook?.size) || 2)));
        const frameCount = gridSize * gridSize;
        const index = Math.min(frameCount - 1, Math.floor(t * frameCount));
        const column = index % gridSize, row = Math.floor(index / gridSize);
        const positionValue = gridSize === 1 ? '0% 0%' :
          `${column * 100 / (gridSize - 1)}% ${row * 100 / (gridSize - 1)}%`;
        if (p.tintImage) {
          p.el.style.maskPosition = positionValue; p.el.style.webkitMaskPosition = positionValue;
        } else {
          p.el.style.backgroundPosition = positionValue;
        }
        if (p.glowEl) {
          p.glowEl.style.backgroundPosition = positionValue;
        }
      }
    }
  } catch (err) {
    console.error('Particle update error:', err);
  } finally {
    requestAnimationFrame(updateParticles);
  }
}
requestAnimationFrame(updateParticles);
function playEffectFunction(square, effectFunction, directionDegrees = 0) {
  // One capture invokes every configured emission at once. Each object is an
  // independent call to the same emitter, with its own random ranges/curves.
  // Emissions are sorted ascending by zIndex so higher values render on top.
  const emissions = [...(effectFunction?.emissions || [])].sort(
    (a, b) => (Number(a.zIndex) || 0) - (Number(b.zIndex) || 0)
  );
  emissions.forEach(settings => emit(settings, square, directionDegrees));
}
function playPieceEffect(square, pieceType, kind, movingTeam, directionDegrees = 0) {
  const team = String(movingTeam || '').toLowerCase();
  const assignment = effectConfig.pieceEffects?.[pieceType];
  // The legacy fallback keeps existing saved configurations usable until the
  // control window next writes its migrated team-specific configuration.
  const configuredPreset = assignment?.[team]?.[kind] || assignment?.[kind];
  const effectFunction = effectConfig.functions?.[configuredPreset] || effectConfig.functions?.[effectConfig.selectedFunction];
  playEffectFunction(square, effectFunction, directionDegrees);
}
function buildPieceTrailRoute(source, destination, pieceType) {
  if (!['queen', 'rook'].includes(pieceType) ||
      !/^[a-h][1-8]$/.test(source) ||
      !/^[a-h][1-8]$/.test(destination)) return [];

  const sourceFile = source.charCodeAt(0) - 97;
  const sourceRank = Number(source[1]) - 1;
  const fileDelta = destination.charCodeAt(0) - 97 - sourceFile;
  const rankDelta = Number(destination[1]) - 1 - sourceRank;
  const distance = Math.max(Math.abs(fileDelta), Math.abs(rankDelta));
  const isDiagonal = Math.abs(fileDelta) === Math.abs(rankDelta);

  if (distance === 0 ||
      (pieceType === 'rook' && fileDelta !== 0 && rankDelta !== 0) ||
      (pieceType === 'queen' && fileDelta !== 0 && rankDelta !== 0 && !isDiagonal)) return [];

  const fileStep = Math.sign(fileDelta);
  const rankStep = Math.sign(rankDelta);
  return Array.from({ length: distance }, (_, index) => {
    const file = String.fromCharCode(97 + sourceFile + fileStep * index);
    const rank = sourceRank + rankStep * index + 1;
    return `${file}${rank}`;
  });
}

function playPieceTrail(source, destination, pieceType, movingTeam) {
  if (!effectsActive || !board?.squares) return;

  const team = String(movingTeam || '').toLowerCase();
  const preset = effectConfig.pieceEffects?.[pieceType]?.[team]?.trail;
  const effectFunction = effectConfig.functions?.[preset];
  if (!preset || !effectFunction) return;

  const routeNames = buildPieceTrailRoute(source, destination, pieceType);
  if (routeNames.length === 0) return;

  const squaresByName = new Map(
    board.squares.map(square => [String(square.name).toLowerCase(), square])
  );
  const route = routeNames.map(name => squaresByName.get(name));
  if (route.some(square => !square)) {
    console.error(`Cannot play ${pieceType} trail: board route contains an unknown square (${source} to ${destination})`);
    return;
  }

  const directionDegrees = movementDegreesFromSquares(source, destination);
  const durationMs = Math.max(0.05, Math.min(10, Number(effectConfig.movementDuration) || 0.5)) * 1000;
  const intervalMs = durationMs / route.length;
  const startedAt = performance.now();
  console.info(
    `[Trail] ${pieceType} ${source}-${destination}: ${route.length} squares, ` +
    `${durationMs.toFixed(0)}ms total, ${intervalMs.toFixed(1)}ms per square`
  );
  route.forEach((square, index) => {
    const deadline = startedAt + intervalMs * index;
    let timer = null;
    const emitSquare = () => {
      if (timer !== null) trailTimers.delete(timer);
      if (!effectsActive) return;
      console.info(`[Trail] ${square.name} at ${(performance.now() - startedAt).toFixed(1)}ms`);
      playEffectFunction(square, effectFunction, directionDegrees);
    };

    if (index === 0) {
      emitSquare();
      return;
    }
    timer = setTimeout(emitSquare, Math.max(0, deadline - performance.now()));
    trailTimers.add(timer);
  });
}
function playSelectedEffect(square) {
  playEffectFunction(square, effectConfig.functions?.[effectConfig.selectedFunction]);
}
function playTeamDeathEffect(square, defeatedTeam) {
  const key = `${String(defeatedTeam || '').toLowerCase()}Die`;
  const configuredPreset = effectConfig.teamEffects?.[key];
  const effectFunction = effectConfig.functions?.[configuredPreset] || effectConfig.functions?.[effectConfig.selectedFunction];
  playEffectFunction(square, effectFunction);
}
const FXManager = {
  triggerPieceEffect(squareName, pieceType, kind, movingTeam, directionDegrees = 0) {
    if (!effectsActive || !squareName || !board?.squares) return;
    const now = Date.now();
    if (squareName.toLowerCase() === lastCapturedSquare && now - lastCaptureTimestamp < 350) return;
    lastCaptureTimestamp = now; lastCapturedSquare = squareName.toLowerCase();
    const sq = board.squares.find(s => s.name.toLowerCase() === squareName.toLowerCase());
    if (sq) playPieceEffect(sq, pieceType, kind, movingTeam, directionDegrees);
  },
  triggerPieceTrail(source, destination, pieceType, movingTeam) {
    playPieceTrail(source, destination, pieceType, movingTeam);
  },
  triggerTeamDeathEffect(squareName, defeatedTeam) {
    if (!effectsActive || !deathEffectsActive || !squareName || !board?.squares) return;
    const sq = board.squares.find(s => s.name.toLowerCase() === squareName.toLowerCase());
    if (sq) playTeamDeathEffect(sq, defeatedTeam);
  }
};

// Global helper for testing effects in devtools or automation
window.triggerTestCapture = (square = 'e4', team = 'WHITE') => {
  FXManager.triggerPieceEffect(square, 'pawn', 'capture', team);
};

window.cvfx.onMainMessage('effect-config', (config) => {
  if (config?.functions) effectConfig = config;
});
window.cvfx.getEffectConfig().then((config) => { if (config?.functions) effectConfig = config; });
window.cvfx.onMainMessage('test-effect', (square) => {
  if (square?.kind === 'preview') {
    // The black editor square supplies a screen position; the ordinary emitter
    // still creates and animates the particles across the normal overlay.
    document.body.classList.add('preview-mode');
    clearTimeout(previewModeTimer);
    previewModeTimer = setTimeout(() => document.body.classList.remove('preview-mode'), 3000);
    playSelectedEffect({ col: Number(square.x) * 8 - .5, row: Number(square.y) * 8 - .5 });
    return;
  }
  const sq = board?.squares?.find(s => s.name.toLowerCase() === String(square).toLowerCase());
  if (sq) playSelectedEffect(sq);
});

function standardPieceType(square) {
  const normalized = String(square || '').toLowerCase();
  const rank = normalized[1];
  if (rank === '2' || rank === '7') return 'pawn';
  if (rank !== '1' && rank !== '8') return null;
  return { a: 'rook', b: 'knight', c: 'bishop', d: 'queen', e: 'king', f: 'bishop', g: 'knight', h: 'rook' }[normalized[0]] || null;
}

function initializePieceTypes(occupiedSquares) {
  pieceTypes = {};
  Object.keys(occupiedSquares || {}).forEach(square => {
    const pieceType = standardPieceType(square);
    if (pieceType) pieceTypes[square.toLowerCase()] = pieceType;
  });
}

function draw() {
  if (!board?.squares) return;
  labels.innerHTML = '';
  if (!labelsVisible) return;

  // Use real-time visually occupied squares (falls back to tracked teams on initial lock)
  const sourceDict = Object.keys(realtimeOccupied).length > 0 ? realtimeOccupied : trackedTeams;

  board.squares.forEach((square) => {
    const color = sourceDict[square.name];
    if (color && color !== 'EMPTY' && color !== 'NONE' && color !== 'UNKNOWN') {
      const label = document.createElement('div');
      const isWhite = color === 'WHITE';
      label.className = `square-label ${isWhite ? 'white' : 'black'}`;
      label.style.left = `${(square.col / 8) * 100}%`;
      label.style.top = `${(square.row / 8) * 100}%`;
      label.textContent = PIECE_NOTATION[pieceTypes[square.name.toLowerCase()]] || 'P';
      labels.appendChild(label);
    }

    const status = squareScanStatus[square.name];
    if (status) {
      const statusLabel = document.createElement('div');
      statusLabel.className = `square-scan-status status-${status.toLowerCase()}`;
      statusLabel.style.left = `${((square.col + 1) / 8) * 100}%`;
      statusLabel.style.top = `${((square.row + 1) / 8) * 100}%`;
      statusLabel.textContent = status;
      labels.appendChild(statusLabel);
    }
  });
}

// Listen for F-key toggle-labels sent from main process
window.cvfx.onMainMessage('toggle-labels', () => {
  if (!effectsActive) return;
  setLabelsVisible(!labelsVisible);
});

window.cvfx.onMainMessage('effects-active', (active) => {
  effectsActive = Boolean(active);
  if (!effectsActive && fxContainer) {
    // Stop any effect already in progress as soon as the app is deactivated.
    fxContainer.replaceChildren();
  }
  if (!effectsActive) {
    trailTimers.forEach(timer => clearTimeout(timer));
    trailTimers.clear();
    // Reset debug display as well so the next active session always starts
    // with F showing it, rather than inheriting a hidden/shown toggle state.
    setLabelsVisible(false);
  }
});

window.cvfx.onMainMessage('death-effects-active', (active) => {
  deathEffectsActive = Boolean(active);
});

// Hide output HUD on startup until labels are enabled
if (output) output.style.display = 'none';

window.cvfx.getEffectsActive().then((active) => {
  effectsActive = active;
});
window.cvfx.getDeathEffectsActive().then((active) => {
  deathEffectsActive = active;
});

window.cvfx.onPythonMessage((msg) => {
  if (msg.type === 'square_scan_status') {
    squareScanStatus = msg.squares || {};
    draw();
  }
  if (msg.type === 'board_locked') {
    board = msg;
    if (msg.tabPlacement === 'bottom') {
      output?.classList.add('placement-bottom');
      boardContainer?.classList.add('tab-bottom');
    } else {
      output?.classList.remove('placement-bottom');
      boardContainer?.classList.remove('tab-bottom');
    }
    draw();
  }
  if (msg.type === 'board_debug') {
    trackedTeams = msg.squares || {};
    realtimeOccupied = msg.realtimeOccupied || {};
    localTeam = String(msg.localTeam || 'WHITE').toUpperCase();
    if (msg.pieceTypeSetup === 'standard') initializePieceTypesOnBoardUpdate = true;
    if (initializePieceTypesOnBoardUpdate || Object.keys(pieceTypes).length === 0) {
      initializePieceTypes(realtimeOccupied);
      initializePieceTypesOnBoardUpdate = false;
    }
    thinking.textContent = msg.thinking || 'Watching the board';
    if (msg.finalAction) action.textContent = msg.finalAction;
    counts.textContent = `You: ${(msg.localTeam || 'WHITE').toLowerCase()} · White: ${msg.pieceCounts?.WHITE ?? 0} · Black: ${msg.pieceCounts?.BLACK ?? 0}`;
    draw();
  }
  if (msg.type === 'move_decision') {
    const source = String(msg.sourceSquare || '').toLowerCase();
    const destination = String(msg.destinationSquare || '').toLowerCase();
    const capturedSquare = String(msg.capturedSquare || destination).toLowerCase();
    const movingTeam = String(msg.movingTeam || '').toUpperCase();
    const capturedTeam = String(trackedTeams[capturedSquare] || '').toUpperCase();
    const movementDirection = movementDegreesFromSquares(source, destination);
    // Unknown types are intentionally treated as pawns; a standard setup
    // populates every opening square without image recognition.
    const pieceType = msg.kind === 'PROMOTION' ? 'queen' : pieceTypes[source] || 'pawn';
    if (source && destination) {
      FXManager.triggerPieceTrail(source, destination, pieceType, movingTeam);
    }
    if (destination) {
      FXManager.triggerPieceEffect(destination, pieceType, msg.isCapture ? 'capture' : 'land', movingTeam, movementDirection);
    }
    if (msg.isCapture) {
      const defeatedTeam = capturedTeam === 'WHITE' || capturedTeam === 'BLACK'
        ? capturedTeam
        : movingTeam === 'WHITE' ? 'BLACK' : movingTeam === 'BLACK' ? 'WHITE' : '';
      if (defeatedTeam) FXManager.triggerTeamDeathEffect(capturedSquare, defeatedTeam);
    }
    if (source) delete pieceTypes[source];
    if (destination) pieceTypes[destination] = pieceType;
    if (msg.kind === 'CASTLING' && destination) {
      const rank = destination[1];
      const kingSide = destination[0] === 'g';
      const rookSource = `${kingSide ? 'h' : 'a'}${rank}`;
      const rookDestination = `${kingSide ? 'f' : 'd'}${rank}`;
      // The backend moves the rook as part of castling, but the overlay only
      // receives the king transition. Mirror that state change so the debug
      // label at f/d remains R instead of falling back to P.
      const rookType = pieceTypes[rookSource] || 'rook';
      delete pieceTypes[rookSource];
      pieceTypes[rookDestination] = rookType;
    }
  }
});
