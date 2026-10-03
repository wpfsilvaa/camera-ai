// Draw the areas (bed, sofa) where lying down must not raise a fall alert.
(() => {
  const stage = $('.zone-stage'), image = $('#zone-image'), canvas = $('#zone-canvas'), context = canvas.getContext('2d');
  let drag = null;
  const zones = () => (settings.fall_zones ||= []);

  function draw(preview) {
    canvas.width = stage.clientWidth; canvas.height = stage.clientHeight;
    context.clearRect(0, 0, canvas.width, canvas.height);
    for (const [x1, y1, x2, y2] of preview ? [...zones(), preview] : zones()) {
      const [x, y, w, h] = [x1 * canvas.width, y1 * canvas.height, (x2 - x1) * canvas.width, (y2 - y1) * canvas.height];
      context.fillStyle = 'rgba(90,160,190,.28)'; context.fillRect(x, y, w, h);
      context.strokeStyle = '#5aa0be'; context.lineWidth = 2; context.strokeRect(x, y, w, h);
    }
    $('#zone-count').textContent = zones().length ? `${zones().length} área(s) marcada(s)` : 'Nenhuma área marcada';
  }

  function point(event) {
    const box = canvas.getBoundingClientRect();
    return [Math.min(1, Math.max(0, (event.clientX - box.left) / box.width)), Math.min(1, Math.max(0, (event.clientY - box.top) / box.height))];
  }
  const rect = ([ax, ay], [bx, by]) => [Math.min(ax, bx), Math.min(ay, by), Math.max(ax, bx), Math.max(ay, by)].map(v => Math.round(v * 1e4) / 1e4);

  canvas.addEventListener('pointerdown', event => { drag = point(event); canvas.setPointerCapture(event.pointerId); });
  canvas.addEventListener('pointermove', event => { if (drag) draw(rect(drag, point(event))); });
  canvas.addEventListener('pointerup', event => {
    if (!drag) return;
    const zone = rect(drag, point(event)); drag = null;
    if (zone[2] - zone[0] > .02 && zone[3] - zone[1] > .02 && zones().length < 10) zones().push(zone);
    draw();
  });
  $('#zone-clear').addEventListener('click', () => { settings.fall_zones = []; draw(); });
  $('#zone-refresh').addEventListener('click', () => window.renderZoneEditor());
  image.addEventListener('load', () => {
    // Zones are fractions of the image: the stage must keep the camera's proportions.
    stage.style.aspectRatio = `${image.naturalWidth} / ${image.naturalHeight}`;
    $('#zone-empty').classList.add('hidden'); draw();
  });
  image.addEventListener('error', () => { $('#zone-empty').classList.remove('hidden'); image.removeAttribute('src'); draw(); });
  window.addEventListener('resize', () => draw());

  window.renderZoneEditor = () => {
    if (!settings) return;
    // A 204 (camera stopped) fails to decode and shows the hint instead.
    image.src = cameraPath(`/api/snapshot?t=${Date.now()}`);
    draw();
  };
})();
