// Draw marked areas over the camera image: where lying down must not raise a fall alert (bed, sofa),
// the restricted areas (fridge) where restricted mode records, and the floor strips in front of them.
// An area is a rectangle [x1, y1, x2, y2] or a polygon [x1, y1, x2, y2, x3, y3, ...] (fractions of the picture), so it can follow the
// camera's angle. Drag an area to move it, drag a corner to reshape it, double-click an edge to add a corner (a corner, to remove it).
(() => {
  const MAX_ZONES = 10, MAX_POINTS = 12, MIN_AREA = .0005, HANDLE = 7, GRAB = 14, CLOSE = 16;
  const clamp = v => Math.min(1, Math.max(0, v));
  const round4 = v => Math.round(v * 1e4) / 1e4;
  // Inside the editor every area is a list of [x, y] corners, clockwise from the top left for a rectangle.
  const toPoints = zone => zone.length === 4 ? [[zone[0], zone[1]], [zone[2], zone[1]], [zone[2], zone[3]], [zone[0], zone[3]]]
    : zone.reduce((list, v, i) => (i % 2 ? list[list.length - 1].push(v) : list.push([v]), list), []);
  const isRect = p => p.length === 4 && p[0][1] === p[1][1] && p[1][0] === p[2][0] && p[2][1] === p[3][1] && p[3][0] === p[0][0] && p[0][0] < p[1][0] && p[0][1] < p[2][1];
  const toZone = p => (isRect(p) ? [p[0][0], p[0][1], p[2][0], p[2][1]] : p.flat()).map(round4);
  const area = p => Math.abs(p.reduce((sum, [ax, ay], i) => sum + ax * p[(i + 1) % p.length][1] - p[(i + 1) % p.length][0] * ay, 0)) / 2;
  const inside = (p, x, y) => p.reduce((hit, [ax, ay], i) => { const [bx, by] = p[(i + 1) % p.length]; return (ay > y) !== (by > y) && x < (bx - ax) * (y - ay) / (by - ay) + ax ? !hit : hit; }, false);
  // Distance (in pixels) from a point to a segment, and which point of it is closest (0..1).
  function segment([ax, ay], [bx, by], [x, y]) {
    const dx = bx - ax, dy = by - ay, length = dx * dx + dy * dy, t = length ? Math.max(0, Math.min(1, ((x - ax) * dx + (y - ay) * dy) / length)) : 0;
    return {distance: Math.hypot(x - ax - t * dx, y - ay - t * dy), t};
  }

  function zoneEditor(root) {
    const key = root.dataset.zones, [r, g, b] = root.dataset.color.split(',');
    const stage = root.querySelector('.zone-stage'), image = root.querySelector('img'), canvas = root.querySelector('canvas'), context = canvas.getContext('2d');
    const empty = root.querySelector('.zone-stage p'), count = root.querySelector('.zone-actions span');
    // Unsaved areas live here: the 3 s status poll replaces `settings` and would drop them.
    let drawn = [], names = [], tool = 'rect', selected = -1, gesture = null, building = [], hover = null;
    const namesKey = root.dataset.names, namesBox = root.querySelector('.zone-names');
    const zones = () => drawn;
    let shownNames = '';
    const changed = () => root.dispatchEvent(new Event('input', {bubbles: true}));   // Marks the settings as not saved yet.

    // Toolbar: how a new area is drawn, and moving everything at once when the camera was bumped.
    const toolbar = document.createElement('div');
    toolbar.className = 'zone-tools';
    toolbar.innerHTML = '<div class="filter-group"><button type="button" class="filter active" data-tool="rect">Retângulo</button><button type="button" class="filter" data-tool="poly">Pontos</button>'
      + '<button type="button" class="filter" data-tool="all" title="Arraste em qualquer lugar da imagem para deslocar todas as áreas, ou use as setas do teclado">Mover todas</button></div>'
      + '<span class="muted small" data-tip></span>';
    stage.before(toolbar);
    const tip = toolbar.querySelector('[data-tip]');
    const tips = {rect: 'Arraste sobre a imagem para desenhar. Clique numa área para movê-la; arraste um canto para deformar.',
      poly: 'Clique nos cantos da área, na ordem. Feche clicando no primeiro ponto, com duplo clique ou em “Concluir”.',
      all: 'Arraste na imagem para deslocar todas as áreas de uma vez (a câmera mexeu). As setas do teclado ajustam.'};
    function setTool(next) {
      tool = next; building = []; gesture = null;
      toolbar.querySelectorAll('[data-tool]').forEach(button => button.classList.toggle('active', button.dataset.tool === tool));
      tip.textContent = tips[tool]; draw();
    }
    toolbar.addEventListener('click', event => { const button = event.target.closest('[data-tool]'); if (button) setTool(button.dataset.tool); });
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
      removeZone(Number(remove.dataset.zoneRemove));
    });
    function removeZone(index) {
      if (index < 0 || index >= drawn.length) return;
      drawn.splice(index, 1); names.splice(index, 1); selected = -1; shownNames = ''; changed(); draw();
    }

    const size = () => [canvas.width, canvas.height];
    const px = ([x, y]) => [x * canvas.width, y * canvas.height];
    function path(points) { points.forEach((p, i) => context[i ? 'lineTo' : 'moveTo'](...px(p))); }

    function draw() {
      canvas.width = stage.clientWidth; canvas.height = stage.clientHeight;
      context.clearRect(0, 0, canvas.width, canvas.height);
      const ink = `rgb(${r},${g},${b})`;
      for (const [index, points] of zones().entries()) {
        const active = index === selected;
        context.beginPath(); path(points); context.closePath();
        context.fillStyle = `rgba(${r},${g},${b},${active ? .4 : .28})`; context.fill();
        context.strokeStyle = ink; context.lineWidth = active ? 3 : 2; context.stroke();
        if (namesKey) {
          const label = (names[index] || `Área ${index + 1}`).slice(0, 24), [x, y] = px(points.reduce((top, p) => (p[1] < top[1] || (p[1] === top[1] && p[0] < top[0]) ? p : top)));
          context.font = '600 13px system-ui, sans-serif'; context.fillStyle = ink;
          context.fillRect(x, y, context.measureText(label).width + 12, 20); context.fillStyle = '#fff'; context.fillText(label, x + 6, y + 14);
        }
        if (active) for (const point of points) {
          const [x, y] = px(point);
          context.beginPath(); context.arc(x, y, HANDLE, 0, Math.PI * 2); context.fillStyle = '#fff'; context.fill(); context.strokeStyle = ink; context.lineWidth = 2; context.stroke();
        }
      }
      if (gesture?.kind === 'rect') {   // The rectangle being dragged out.
        const [[ax, ay], [bx, by]] = [gesture.start, gesture.now];
        context.fillStyle = `rgba(${r},${g},${b},.2)`; context.strokeStyle = ink; context.lineWidth = 2; context.setLineDash([6, 4]);
        context.fillRect(...px([Math.min(ax, bx), Math.min(ay, by)]), Math.abs(bx - ax) * canvas.width, Math.abs(by - ay) * canvas.height);
        context.strokeRect(...px([Math.min(ax, bx), Math.min(ay, by)]), Math.abs(bx - ax) * canvas.width, Math.abs(by - ay) * canvas.height); context.setLineDash([]);
      }
      if (building.length) {   // The polygon being clicked out, with a line to the pointer.
        context.beginPath(); path(building); if (hover) context.lineTo(...px(hover));
        context.strokeStyle = ink; context.lineWidth = 2; context.setLineDash([6, 4]); context.stroke(); context.setLineDash([]);
        building.forEach((point, i) => { const [x, y] = px(point); context.beginPath(); context.arc(x, y, i ? 4 : HANDLE, 0, Math.PI * 2); context.fillStyle = i ? ink : '#fff'; context.fill(); context.strokeStyle = ink; context.stroke(); });
      }
      renderNames();
      const parts = [zones().length ? `${zones().length} área(s) marcada(s)` : 'Nenhuma área marcada'];
      if (building.length) parts.push(building.length >= 3 ? `${building.length} pontos · “Concluir” fecha a área` : `${building.length} ponto(s)`);
      count.textContent = parts.join(' · ');
      finish.classList.toggle('hidden', building.length < 3);
    }
    const finish = document.createElement('button');
    finish.type = 'button'; finish.className = 'text-button hidden'; finish.textContent = 'Concluir';
    count.after(finish);

    function point(event) {
      const box = canvas.getBoundingClientRect();
      return [clamp((event.clientX - box.left) / box.width), clamp((event.clientY - box.top) / box.height)];
    }
    // What is under the pointer: a corner, an edge (to add a corner), the inside of an area, or nothing.
    function pick(p) {
      const [w, h] = size(), at = ([x, y]) => [x * w, y * h], target = at(p);
      const order = [...zones().keys()].reverse();   // The one drawn last is on top.
      for (const index of [selected, ...order].filter(i => i >= 0)) {
        const found = zones()[index].findIndex(corner => Math.hypot(...at(corner).map((v, i) => v - target[i])) <= GRAB);
        if (found >= 0) return {index, corner: found};
      }
      for (const index of order) {
        const points = zones()[index];
        for (let i = 0; i < points.length; i++) {
          const {distance, t} = segment(at(points[i]), at(points[(i + 1) % points.length]), target);
          if (distance <= 8 && index === selected) return {index, edge: i, t};
        }
      }
      for (const index of order) if (inside(zones()[index], ...p)) return {index, body: true};
      return null;
    }
    // Shift a set of areas by (dx, dy) without letting any corner leave the picture.
    function shift(indexes, dx, dy) {
      const flat = indexes.flatMap(i => drawn[i]);
      dx = Math.min(Math.max(dx, -Math.min(...flat.map(p => p[0]))), 1 - Math.max(...flat.map(p => p[0])));
      dy = Math.min(Math.max(dy, -Math.min(...flat.map(p => p[1]))), 1 - Math.max(...flat.map(p => p[1])));
      for (const i of indexes) drawn[i] = drawn[i].map(([x, y]) => [x + dx, y + dy]);
    }
    function addZone(points) {
      if (zones().length >= MAX_ZONES || area(points) < MIN_AREA) return false;
      drawn.push(points.map(([x, y]) => [round4(x), round4(y)])); names.length = drawn.length - 1; names.push('');
      selected = drawn.length - 1; shownNames = ''; changed(); return true;
    }
    function closePolygon() {
      if (building.length >= 3) addZone(building);
      building = []; draw();
    }
    finish.addEventListener('click', closePolygon);

    canvas.addEventListener('pointerdown', event => {
      const p = point(event), hit = pick(p);
      canvas.focus({preventScroll: true});
      if (tool === 'all') { if (zones().length) { gesture = {kind: 'all', last: p}; canvas.setPointerCapture(event.pointerId); } return; }
      if (tool === 'poly' && building.length) {   // Clicking the first point again closes the area.
        const [w, h] = size(), first = building[0];
        if (building.length >= 3 && Math.hypot((first[0] - p[0]) * w, (first[1] - p[1]) * h) <= CLOSE) { closePolygon(); return; }
        if (building.length < MAX_POINTS) building.push(p);
        draw(); return;
      }
      if (hit?.corner !== undefined) { selected = hit.index; gesture = {kind: 'corner', index: hit.index, corner: hit.corner}; canvas.setPointerCapture(event.pointerId); draw(); return; }
      if (hit?.body || hit?.edge !== undefined) { selected = hit.index; gesture = {kind: 'move', last: p, moved: false}; canvas.setPointerCapture(event.pointerId); draw(); return; }
      selected = -1;
      if (tool === 'poly') { building = [p]; draw(); return; }
      gesture = {kind: 'rect', start: p, now: p}; canvas.setPointerCapture(event.pointerId); draw();
    });
    canvas.addEventListener('pointermove', event => {
      const p = point(event);
      hover = p;
      if (!gesture) {
        const hit = pick(p);
        canvas.style.cursor = tool === 'all' ? 'move' : hit?.corner !== undefined ? 'grab' : hit ? 'move' : 'crosshair';
        if (building.length) draw();
        return;
      }
      if (gesture.kind === 'rect') gesture.now = p;
      else if (gesture.kind === 'corner') drawn[gesture.index][gesture.corner] = p;
      else { shift(gesture.kind === 'all' ? [...drawn.keys()] : [selected], p[0] - gesture.last[0], p[1] - gesture.last[1]); gesture.last = p; gesture.moved = true; }
      draw();
    });
    canvas.addEventListener('pointerup', () => {
      if (!gesture) return;
      const done = gesture; gesture = null;
      if (done.kind === 'rect') {
        const [[ax, ay], [bx, by]] = [done.start, done.now];
        if (Math.abs(bx - ax) > .02 && Math.abs(by - ay) > .02) addZone([[Math.min(ax, bx), Math.min(ay, by)], [Math.max(ax, bx), Math.min(ay, by)], [Math.max(ax, bx), Math.max(ay, by)], [Math.min(ax, bx), Math.max(ay, by)]]);
      } else if (done.kind === 'corner' || done.moved) changed();
      draw();
    });
    canvas.addEventListener('pointerleave', () => { hover = null; if (building.length) draw(); });
    canvas.addEventListener('dblclick', event => {
      if (tool === 'poly' && building.length >= 2) { building.pop(); closePolygon(); return; }   // The first click of the double click already added a point.
      const hit = pick(point(event));
      if (!hit) return;
      const points = drawn[hit.index];
      if (hit.corner !== undefined && points.length > 3) points.splice(hit.corner, 1);
      else if (hit.edge !== undefined && points.length < MAX_POINTS) points.splice(hit.edge + 1, 0, point(event));
      else return;
      changed(); draw();
    });
    canvas.tabIndex = 0;
    canvas.addEventListener('keydown', event => {
      if (event.key === 'Escape' && building.length) { building = []; draw(); return; }
      if (event.key === 'Enter' && building.length >= 3) { closePolygon(); return; }
      if ((event.key === 'Delete' || event.key === 'Backspace') && selected >= 0) { event.preventDefault(); removeZone(selected); return; }
      const step = event.shiftKey ? .02 : .004, move = {ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step]}[event.key];
      if (!move || !drawn.length) return;
      event.preventDefault();
      shift(selected >= 0 && tool !== 'all' ? [selected] : [...drawn.keys()], ...move); changed(); draw();
    });
    root.querySelector('[data-zone-clear]').addEventListener('click', () => { drawn = []; names = []; building = []; selected = -1; shownNames = ''; changed(); draw(); });
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
    tip.textContent = tips.rect;

    return {
      key, namesKey, value: () => drawn.map(toZone), nameValues: () => drawn.map((_, i) => (names[i] || '').trim()),
      // Start over from the saved areas (page opened, settings saved, camera switched).
      reset() { drawn = (settings[key] || []).map(toPoints); names = drawn.map((_, i) => (settings[namesKey] || [])[i] || ''); selected = -1; building = []; shownNames = ''; loadImage(); },
    };
  }

  const editors = [...document.querySelectorAll('.zone-editor[data-zones]')].map(zoneEditor);
  window.renderZoneEditor = () => { if (settings) editors.forEach(editor => editor.reset()); };
  // Areas drawn on the page, merged into the settings when saving.
  window.zoneDrafts = () => Object.fromEntries(editors.flatMap(editor => [[editor.key, editor.value()], ...(editor.namesKey ? [[editor.namesKey, editor.nameValues()]] : [])]));
})();
