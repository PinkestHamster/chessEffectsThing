/**
 * scripts/run_tests.js
 *
 * Cross-platform test runner for Chess Vision FX.
 * Runs: Python pytest suite
 * Called by: npm test
 */

const { spawnSync } = require('child_process');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const PYTHON_TESTS = path.join(ROOT, 'python', 'tests');

let failed = false;

console.log('═══════════════════════════════════════════════');
console.log('  Chess Vision FX – Test Suite');
console.log('═══════════════════════════════════════════════\n');

// ── Python tests ──────────────────────────────────────────
console.log('▶ Running Python unit tests (pytest)…\n');

// Try to find pytest; fall back to python -m pytest
const result = spawnSync(
  'python',
  ['-m', 'pytest', PYTHON_TESTS, '-v', '--tb=short', '--no-header'],
  { cwd: ROOT, stdio: 'inherit', shell: true }
);

if (result.status !== 0) {
  console.error('\n✗ Python tests failed');
  failed = true;
} else {
  console.log('\n✓ Python tests passed');
}

console.log('\n═══════════════════════════════════════════════');
console.log(failed ? '  OVERALL: FAILED' : '  OVERALL: PASSED');
console.log('═══════════════════════════════════════════════\n');

process.exit(failed ? 1 : 0);
