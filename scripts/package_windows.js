const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const RELEASE_DIR = path.join(ROOT, 'release');
const OUTPUT_EXE = path.join(ROOT, 'Chess-Vision-FX.exe');
const OUTPUT_SHORTCUT = path.join(ROOT, 'Chess-Vision-FX.lnk');
const builderCli = path.join(ROOT, 'node_modules', 'electron-builder', 'cli.js');
const powershell = process.env.SystemRoot
  ? path.join(process.env.SystemRoot, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
  : 'powershell.exe';

function runPowerShell(script, args) {
  const result = spawnSync(powershell, [
    '-NoProfile',
    '-NonInteractive',
    '-ExecutionPolicy',
    'Bypass',
    '-File',
    path.join(__dirname, script),
    ...args,
  ], { cwd: ROOT, stdio: 'inherit' });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status || 1);
}

runPowerShell('create_windows_icon.ps1', [path.join(ROOT, 'images', 'chess-vision.ico')]);

const result = spawnSync(process.execPath, [builderCli, '--win', 'portable'], {
  cwd: ROOT,
  stdio: 'inherit',
});

if (result.error) throw result.error;
if (result.status !== 0) process.exit(result.status || 1);

const artifacts = fs.readdirSync(RELEASE_DIR)
  .filter(name => /^Chess-Vision-FX-.*-portable\.exe$/i.test(name))
  .map(name => path.join(RELEASE_DIR, name))
  .sort((a, b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs);

if (artifacts.length === 0) {
  throw new Error(`No portable Windows executable found in ${RELEASE_DIR}.`);
}

fs.copyFileSync(artifacts[0], OUTPUT_EXE);
console.log(`Portable app copied to ${OUTPUT_EXE}`);
runPowerShell('create_windows_shortcut.ps1', [OUTPUT_EXE, OUTPUT_SHORTCUT]);
console.log(`Shortcut created at ${OUTPUT_SHORTCUT}`);
