// Person-detector choice: shows whether the selected model/engine is ready, downloading or failed.
const DETECTOR_MB = {n: 6, s: 20, m: 44, l: 53};
let detectorTimer = null;
async function refreshDetectorStatus() {
  clearTimeout(detectorTimer);
  const form = $('#settings-form'), note = $('#detector-status');
  if (!form || !note || !isAdmin()) return;
  const model = form.elements.detector_model.value, engine = form.elements.detector_engine.value;
  const query = new URLSearchParams({model, engine, size: form.elements.detection_size.value, pose: form.elements.fall_detection_enabled?.checked ? 'true' : 'false'});
  try {
    const data = await api(`/api/detectors/state?${query}`);
    const needs = model !== 'n' ? `baixa ${DETECTOR_MB[model]} MB` : '';
    const convert = engine !== 'pytorch' ? 'converte uma vez' : '';
    if (data.state === 'ready') note.textContent = 'Pronto: este modelo já está disponível neste servidor.';
    else if (data.state === 'preparing') { note.textContent = `Preparando: ${data.message || 'aguarde'}. A câmera segue com o modelo atual até terminar.`; detectorTimer = setTimeout(refreshDetectorStatus, 3000); }
    else if (data.state === 'error') note.textContent = `Falhou: ${data.message}. Salve de novo para tentar outra vez.`;
    else note.textContent = [needs, convert].filter(Boolean).length ? `Ao salvar: ${[needs, convert].filter(Boolean).join(' e ')} (só na primeira vez).` : 'Já disponível neste servidor.';
  } catch (error) { note.textContent = ''; }
}
document.addEventListener('change', event => {
  if (['detector_model', 'detector_engine', 'detection_size', 'fall_detection_enabled'].includes(event.target.name)) refreshDetectorStatus();
});
window.addEventListener('hashchange', () => { if (location.hash === '#settings') refreshDetectorStatus(); });
document.addEventListener('click', event => { if (event.target.closest('#save-settings')) setTimeout(refreshDetectorStatus, 1500); });
setTimeout(refreshDetectorStatus, 2500);

// USB cameras plugged into the server, offered as suggestions for the camera address.
async function loadUsbCameras() {
  const list = $('#usb-cameras');
  if (!list || !isAdmin()) return;
  try {
    const data = await api('/api/cameras/usb');
    list.replaceChildren(...data.cameras.map(camera => Object.assign(new Option(camera.name, camera.source), {label: camera.name})));
  } catch (error) { /* the list is only a convenience */ }
}
window.addEventListener('hashchange', () => { if (location.hash === '#settings') loadUsbCameras(); });
setTimeout(loadUsbCameras, 2500);
