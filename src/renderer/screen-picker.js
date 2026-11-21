const hint = document.getElementById('hint');
let pickerReady = false;
let pickSubmitted = false;

window.cvfx.onScreenColorPickReady(() => {
  pickerReady = true;
  hint.textContent = 'Click a color anywhere on your desktop · Esc to cancel';
});

document.addEventListener('click', event => {
  if (!pickerReady || pickSubmitted) return;
  pickSubmitted = true;
  hint.textContent = 'Sampling color…';
  window.cvfx.completeScreenColorPickAt(event.clientX, event.clientY);
});

document.addEventListener('keydown', event => {
  if (event.key !== 'Escape') return;
  event.preventDefault();
  window.cvfx.cancelScreenColorPick();
});
document.addEventListener('contextmenu', event => {
  event.preventDefault();
  window.cvfx.cancelScreenColorPick();
});
