// Draw marked areas over the camera image: where lying down must not raise a fall alert (bed, sofa),
// and the restricted areas (fridge) where restricted mode records.
(() => {
  function zoneEditor(root) {
    const key = root.dataset.zones, [r, g, b] = root.dataset.color.split(',');
    const stage = root.querySelector('.zone-stage'), image = root.querySelector('img'), canvas = root.querySelector('canvas'), context = canvas.getContext('2d');
    const empty = root.querySelector('.zone-stage p'), count = root.querySelector('.zone-actions span');
    // Unsaved areas live here: the 3 s status poll replaces `settings` and would drop them.
    let drag = null, drawn = [], names = [];
    const namesKey = root.dataset.names, namesBox = root.querySelector('.zone-names');
    const zones = () => drawn;
    let shownNames = '';
    // One name field per marked area (restricted areas only), so reports can say "geladeira" and "armário".
    function renderNames() {
      if (!namesBox) return;
      const signature = `${zones().length}`;
      if (signature === shownNames) return;
      shownNames = signature;
      namesBox.innerHTML = zones().map((_, i) => `<div class="zone-name"><span>${i + 1}</span><input maxlength="30" placeholder="Nome da área ${i + 1} (ex.: Geladeira)" value="${escapeHTML(names[i] || '')}" data-zone-name="${i}"><button type="button" class="text-button danger" data-zone-remove="${i}">Remover</button></div>`).join('');
    }
    namesBox?.addEventListener('input', event => { const field = event.target.closest('[data-zone-name]'); if (field) { names[Number(field.dataset.zoneName)] = field.value; draw(); } });
    namesBox?.addEventListener('click', event => {
      const remove = event.target.closest('[data-zone-remove]');
      if (!remove) return;
      const index = Number(remove.dataset.zoneRemove);
      drawn.splice(index, 1); names.splice(index, 1); shownNames = ''; draw();
    });

    function draw(preview) {
      canvas.width = stage.clientWidth; canvas.height = stage.clientHeight;
      context.clearRect(0, 0, canvas.width, canvas.height);
      for (const [index, [x1, y1, x2, y2]] of (preview ? [...zones(), preview] : zones()).entries()) {
        const [x, y, w, h] = [x1 * canvas.width, y1 * canvas.height, (x2 - x1) * canvas.width, (y2 - y1) * canvas.height];
        context.fillStyle = `rgba(${r},${g},${b},.28)`; context.fillRect(x, y, w, h);
        context.strokeStyle = `rgb(${r},${g},${b})`; context.lineWidth = 2; context.strokeRect(x, y, w, h);
        if (namesKey) {
          const label = (names[index] || `Área ${index + 1}`).slice(0, 24);
          context.font = '600 13px system-ui, sans-serif'; context.fillStyle = `rgb(${r},${g},${b})`;
          context.fillRect(x, y, context.measureText(label).width + 12, 20); context.fillStyle = '#fff'; context.fillText(label, x + 6, y + 14);
        }
      }
      renderNames();
      count.textContent = zones().length ? `${zones().length} área(s) marcada(s)` : 'Nenhuma área marcada';
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
      if (zone[2] - zone[0] > .02 && zone[3] - zone[1] > .02 && zones().length < 10) { zones().push(zone); names.length = zones().length - 1; names.push(''); }
      draw();
    });
    root.querySelector('[data-zone-clear]').addEventListener('click', () => { drawn = []; names = []; shownNames = ''; draw(); });
    root.querySelector('[data-zone-refresh]').addEventListener('click', () => loadImage());
    image.addEventListener('load', () => {
      // Zones are fractions of the image: the stage must keep the camera's proportions.
      stage.style.aspectRatio = `${image.naturalWidth} / ${image.naturalHeight}`;
      empty.classList.add('hidden'); draw();
    });
    image.addEventListener('error', () => { empty.classList.remove('hidden'); image.removeAttribute('src'); draw(); });
    window.addEventListener('resize', () => draw());

    function loadImage() {
      // A 204 (camera stopped) fails to decode and shows the hint instead.
      image.src = cameraPath(`/api/snapshot?t=${Date.now()}`);
      draw();
    }

    return {
      key, namesKey, value: () => drawn.map(zone => [...zone]), nameValues: () => drawn.map((_, i) => (names[i] || '').trim()),
      // Start over from the saved areas (page opened, settings saved, camera switched).
      reset() { drawn = (settings[key] || []).map(zone => [...zone]); names = drawn.map((_, i) => (settings[namesKey] || [])[i] || ''); shownNames = ''; loadImage(); },
    };
  }

  const editors = [...document.querySelectorAll('.zone-editor[data-zones]')].map(zoneEditor);
  window.renderZoneEditor = () => { if (settings) editors.forEach(editor => editor.reset()); };
  // Areas drawn on the page, merged into the settings when saving.
  window.zoneDrafts = () => Object.fromEntries(editors.flatMap(editor => [[editor.key, editor.value()], ...(editor.namesKey ? [[editor.namesKey, editor.nameValues()]] : [])]));
})();
