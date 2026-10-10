// Tela do notebook da cozinha: botões grandes para chamar a família e o rosto de quem atendeu.
(() => {
  const $ = id => document.getElementById(id);
  const screen = $('screen');
  let last = {call: {state: 'idle'}}, confirming = false, face = null, faceTimer = null;
  let build = null, greetedId = null, greetTimer = null;
  const DEFAULT_CFG = {slide: 15, awake: 30, sounds: 'normal', calendar: true, hints: [], black: true};
  const cfg = () => ({...DEFAULT_CFG, ...(last.cfg || {})});

  // Sounds generated here (no files): confirm beep, ringback while calling, chimes when answered or over.
  let audio = null, ringTimer = null, shownView = 'idle';
  function tone(freq, at, length, volume = 0.22) {
    volume *= {off: 0, low: 0.4, normal: 1, high: 1.8}[cfg().sounds] ?? 1;
    if (volume <= 0) return;
    audio = audio || new (window.AudioContext || window.webkitAudioContext)();
    if (audio.state === 'suspended') audio.resume().catch(() => {});
    const osc = audio.createOscillator(), gain = audio.createGain(), start = audio.currentTime + at;
    osc.type = 'sine'; osc.frequency.value = freq;
    gain.gain.setValueAtTime(0, start);
    gain.gain.linearRampToValueAtTime(volume, start + 0.02);
    gain.gain.setValueAtTime(volume, start + length - 0.05);
    gain.gain.linearRampToValueAtTime(0, start + length);
    osc.connect(gain).connect(audio.destination);
    osc.start(start); osc.stop(start + length + 0.02);
  }
  const quiet = () => document.documentElement.dataset.night === '1' ? 0.4 : 1;   // Softer at night, never silent.
  const sounds = {
    press: () => tone(660, 0, 0.12, 0.2 * quiet()),
    ring: kind => kind === 'panic'
      ? [0, 0.28, 0.56].forEach(at => tone(880, at, 0.18, 0.3))                       // Urgent: three quick high beeps.
      : [0, 0.55].forEach(at => tone(425, at, 0.4, 0.22 * quiet())),                   // Calm "tu-tu" like a phone ringing.
    answered: () => { tone(523, 0, 0.16, 0.22 * quiet()); tone(784, 0.18, 0.28, 0.22 * quiet()); },
    over: () => { tone(784, 0, 0.16, 0.2 * quiet()); tone(523, 0.18, 0.3, 0.2 * quiet()); },
  };
  function soundFor(view, call) {
    if (view === shownView) return;
    const before = shownView;
    shownView = view;
    clearInterval(ringTimer); ringTimer = null;
    try {
      if (view === 'ringing') {
        sounds.ring(call.kind);
        ringTimer = setInterval(() => sounds.ring(call.kind), call.kind === 'panic' ? 1600 : 3000);
      } else if (view === 'answered') sounds.answered();
      else if (view === 'over' && before !== 'idle') sounds.over();
    } catch { /* No audio device: the screen still shows the state. */ }
  }
  const VIGIA = {off: 'Vigia desativado', resting: 'Vigia ativo', analysing: 'Vigia analisando', scheduled: 'Vigia agendado'};

  const post = path => fetch(path, {method: 'POST', headers: {'X-Kiosk': '1', 'Content-Type': 'application/json'}, body: '{}'});

  async function press(kind) {
    try { sounds.press(); } catch { /* ignore */ }
    const response = await fetch('/call', {method: 'POST', headers: {'X-Kiosk': '1', 'Content-Type': 'application/json'}, body: JSON.stringify({kind})});
    if (!response.ok) { $('note').textContent = 'Não foi possível chamar agora. Tente de novo.'; $('note').classList.remove('hidden'); }
    confirming = false;
    await poll();
  }

  $('btn-call').onclick = () => press('call');
  $('btn-panic').onclick = () => { confirming = true; render(); };
  $('confirm-yes').onclick = () => press('panic');
  $('confirm-no').onclick = () => { confirming = false; render(); };
  $('btn-cancel').onclick = async () => { await post('/cancel'); poll(); };
  $('btn-end').onclick = async () => { await post('/cancel'); poll(); };

  function clock() {
    const now = new Date();
    $('clock').textContent = now.toLocaleTimeString('pt-BR', {hour: '2-digit', minute: '2-digit'});
    $('date').textContent = now.toLocaleDateString('pt-BR', {weekday: 'long', day: 'numeric', month: 'long'});
    $('frame-clock').textContent = $('clock').textContent; $('frame-date').textContent = now.toLocaleDateString('pt-BR', {weekday: 'long', day: 'numeric'});
  }

  function render() {
    const {call, linked, enabled, battery, plugged} = last;
    $('battery').classList.toggle('hidden', battery == null);
    $('battery').textContent = battery == null ? '' : `${plugged ? '⚡' : '🔋'} ${battery}%`;
    let view = 'idle';
    if (call.state === 'ringing') view = 'ringing';
    else if (call.state === 'answered') view = 'answered';
    else if (call.state === 'ended' || call.state === 'missed') view = 'over';
    else if (confirming) view = 'confirm';
    screen.dataset.view = view;
    soundFor(view, call);
    document.documentElement.dataset.night = last.night ? '1' : '0';
    const state = VIGIA[last.vigia] ? last.vigia : '';
    screen.dataset.vigia = state;
    $('vigia').classList.toggle('hidden', !state);
    $('vigia-text').textContent = VIGIA[state] || '';
    document.querySelector('.vi-shield').classList.toggle('hidden', state === 'analysing');
    document.querySelector('.vi-eye').classList.toggle('hidden', state !== 'analysing');
    applyMode(view);
    greet(view);
    renderReminder();
    renderCalendar();
    if (last.build) { if (build === null) build = last.build; else if (build !== last.build) location.reload(); }

    $('btn-call').classList.toggle('hidden', !enabled.call);
    $('btn-panic').classList.toggle('hidden', !enabled.panic);
    $('btn-call').disabled = $('btn-panic').disabled = !linked;
    const note = !linked ? 'Chamada indisponível no momento. Se precisar, use o telefone.' : !enabled.call && !enabled.panic ? 'Chamada pela tela desativada.' : '';
    $('note').textContent = note;
    $('note').classList.toggle('hidden', !note);
    $('ringing-title').textContent = call.kind === 'panic' ? 'Pedindo ajuda…' : 'Chamando a família…';
    if (view === 'answered') {
      $('answered-title').textContent = `${call.answered_by} atendeu`;
      $('avatar').textContent = (call.answered_by || '?').trim().slice(0, 1).toUpperCase();
      watchFace(true);
    } else watchFace(false);
    if (view === 'over') {
      $('over-title').textContent = call.state === 'missed' ? 'Ninguém atendeu' : 'Chamada encerrada';
      $('over-text').textContent = call.state === 'missed' ? 'Tente de novo daqui a pouco ou use o telefone.' : '';
    }
  }

  // "Bom dia, Waldemar" for a few seconds when a registered person is recognised; on their birthday a longer party.
  const BIRTHDAY_LINES = ['Que o seu dia seja cheio de carinho e alegria!', 'Todo mundo aqui torce por você hoje!', 'Hoje o dia é todo seu. Aproveite!', 'Um abraço bem apertado da família toda!'];
  function party() {
    const box = $('confetti');
    box.innerHTML = Array.from({length: 46}, (_, i) => `<i style="left:${(i * 2.2 + Math.random() * 2).toFixed(1)}vw;background:hsl(${(i * 47) % 360} 85% 60%);animation-duration:${(4 + Math.random() * 5).toFixed(1)}s;animation-delay:${(Math.random() * 3).toFixed(1)}s"></i>`).join('');
    box.classList.remove('hidden');
  }
  function greet(view) {
    const pairs = [['greeting', 'greeting-sub'], ['frame-greeting', 'frame-greeting-sub']];
    const hide = () => { pairs.flat().forEach(id => $(id).classList.add('hidden')); $('confetti').classList.add('hidden'); $('confetti').innerHTML = ''; };
    if (view !== 'idle') { hide(); return; }
    if (last.greet && last.greet.id !== greetedId) {
      greetedId = last.greet.id;
      const hour = new Date().getHours(), period = hour >= 5 && hour < 12 ? 'Bom dia' : hour >= 12 && hour < 18 ? 'Boa tarde' : 'Boa noite', birthday = !!last.greet.birthday;
      const text = birthday ? `🎂 Feliz aniversário, ${last.greet.name}!` : `${period}, ${last.greet.name}`;
      const extra = birthday ? `${last.greet.age ? `Hoje você completa ${last.greet.age} anos. ` : ''}${BIRTHDAY_LINES[last.greet.id % BIRTHDAY_LINES.length]}` : '';
      for (const [headline, sub] of pairs) {
        $(headline).textContent = text; $(headline).classList.toggle('birthday', birthday); $(headline).classList.remove('hidden');
        $(sub).textContent = extra; $(sub).classList.toggle('hidden', !birthday);
      }
      if (birthday) party(); else $('confetti').classList.add('hidden');
      clearTimeout(greetTimer);
      greetTimer = setTimeout(hide, birthday ? 25000 : 10000);
    }
  }

  // Reminders left in the app: cycled every few seconds while there is more than one.
  let remIndex = 0, remKey = '';
  function renderReminder() {
    const items = last.reminders || [], box = $('reminders');
    box.classList.toggle('hidden', !items.length || screen.dataset.view !== 'idle');
    $('frame-reminder').classList.toggle('hidden', !items.length);
    if (!items.length) { remKey = ''; return; }
    remIndex %= items.length;
    const item = items[remIndex], key = `${item.i}:${remIndex}:${items.length}`;
    if (key === remKey) return;
    remKey = key;
    $('rem-text').textContent = item.t;
    const until = new Date(item.e * 1000), same = until.toDateString() === new Date().toDateString();
    $('rem-meta').textContent = `${item.a ? `${item.a} · ` : ''}até ${same ? '' : until.toLocaleDateString('pt-BR', {weekday: 'short', day: 'numeric'}) + ' '}${until.toLocaleTimeString('pt-BR', {hour: '2-digit', minute: '2-digit'})}`;
    $('fr-text').textContent = item.t; $('fr-meta').textContent = $('rem-meta').textContent;
    $('rem-dots').innerHTML = items.length > 1 ? items.map((_, i) => `<i class="${i === remIndex ? 'on' : ''}"></i>`).join('') : '';
  }
  setInterval(() => { if ((last.reminders || []).length > 1) { remIndex++; renderReminder(); } }, 9000);

  // Photo frame --------------------------------------------------------------
  // By day an idle screen shows the family photos; at night it is black. Touch, mouse or key brings the buttons back.
  let slideMs = 0;
  let awakeUntil = 0, swallowClick = false, order = [], active = 'a', slideTimer = null, hintTimer = null, hintIndex = 0, lastMove = 0;

  function wake() { awakeUntil = Date.now() + cfg().awake * 1000; render(); }
  document.addEventListener('pointerdown', event => {
    if (screen.dataset.mode !== 'ui') { swallowClick = true; event.preventDefault(); event.stopPropagation(); }
    wake();
  }, true);
  document.addEventListener('click', event => { if (swallowClick) { swallowClick = false; event.preventDefault(); event.stopPropagation(); } }, true);
  document.addEventListener('keydown', wake, true);
  document.addEventListener('pointermove', event => { if (Date.now() - lastMove > 500 && (Math.abs(event.movementX) + Math.abs(event.movementY) > 3)) { lastMove = Date.now(); wake(); } }, true);

  function nextSlide() {
    const photos = last.photos || [];
    if (!photos.length) return;
    order = order.filter(id => photos.includes(id));
    if (!order.length) order = [...photos].sort(() => Math.random() - 0.5);
    const id = order.shift(), incoming = active === 'a' ? 'b' : 'a', el = $('slide-' + incoming), outgoing = $('slide-' + active), img = el.querySelector('img');
    img.onload = () => {
      el.querySelector('.back').style.backgroundImage = `url(/photo/${id}.jpg)`;
      img.style.setProperty('--kb', `${30 + Math.random() * 40}% ${30 + Math.random() * 40}%`);
      el.classList.remove('leaving'); el.classList.add('on');
      outgoing.classList.remove('on'); outgoing.classList.add('leaving');
      setTimeout(() => outgoing.classList.remove('leaving'), 1800);
      active = incoming;
    };
    img.src = `/photo/${id}.jpg`;
  }

  function hints() {
    const list = ['Para falar com a família, toque na tela ou mexa o mouse', 'Precisa de ajuda? Toque na tela e escolha “Preciso de ajuda”'];
    const now = new Date(), today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const same = (a, b) => a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
    for (const day of specialDays(now.getFullYear())) if (same(day.date, today)) list.push(`Hoje é ${day.name}`);
    for (const b of last.bdays || []) {
      const [m, d] = b.d.split('-').map(Number);
      if (m - 1 === today.getMonth() && d === today.getDate()) list.push(`🎂 Hoje é aniversário de ${b.n}!`);
      else if (same(new Date(today.getFullYear(), m - 1, d), addDays(today, 1))) list.push(`🎂 Amanhã é aniversário de ${b.n}`);
    }
    list.push(...cfg().hints);
    list.push(now.toLocaleDateString('pt-BR', {weekday: 'long', day: 'numeric', month: 'long'}));
    return list;
  }

  function startFrame(on) {
    if (on && !slideTimer) {
      slideMs = cfg().slide * 1000;
      nextSlide(); slideTimer = setInterval(nextSlide, slideMs);
      const showHint = () => {
        const list = hints(), box = $('frame-hint');
        box.style.opacity = 0;
        setTimeout(() => { hintIndex = (hintIndex + 1) % list.length; box.textContent = list[hintIndex]; box.style.opacity = 1; }, 600);
      };
      showHint(); hintTimer = setInterval(showHint, 9000);
    } else if (!on && slideTimer) {
      clearInterval(slideTimer); clearInterval(hintTimer); slideTimer = hintTimer = null;
    }
  }

  function applyMode(view) {
    const awake = Date.now() < awakeUntil, photos = last.photos || [];
    let mode = 'ui';
    if (view === 'idle' && last.frame && !awake) mode = last.night && cfg().black ? 'black' : photos.length ? 'frame' : 'ui';
    if (slideTimer && slideMs !== cfg().slide * 1000) startFrame(false);   // The interval changed in the settings.
    screen.dataset.mode = mode;
    $('frame').classList.toggle('hidden', mode !== 'frame');
    startFrame(mode === 'frame');
  }

  // Calendar: month grid, national holidays (computed here, no internet) and the registered birthdays.
  function easter(year) {
    const a = year % 19, b = Math.floor(year / 100), c = year % 100, d = Math.floor(b / 4), e = b % 4, f = Math.floor((b + 8) / 25), g = Math.floor((b - f + 1) / 3),
      h = (19 * a + b - d - g + 15) % 30, i = Math.floor(c / 4), k = c % 4, l = (32 + 2 * e + 2 * i - h - k) % 7, m = Math.floor((a + 11 * h + 22 * l) / 451),
      month = Math.floor((h + l - 7 * m + 114) / 31), day = ((h + l - 7 * m + 114) % 31) + 1;
    return new Date(year, month - 1, day);
  }
  const addDays = (date, days) => new Date(date.getFullYear(), date.getMonth(), date.getDate() + days);
  const nthSunday = (year, month, n) => { const first = new Date(year, month, 1); return new Date(year, month, 1 + ((7 - first.getDay()) % 7) + 7 * (n - 1)); };
  function specialDays(year) {
    const e = easter(year), list = [
      [new Date(year, 0, 1), 'Confraternização Universal', 'holiday'], [addDays(e, -48), 'Carnaval (segunda)', 'date'], [addDays(e, -47), 'Carnaval', 'holiday'],
      [addDays(e, -2), 'Sexta-feira Santa', 'holiday'], [e, 'Páscoa', 'date'], [new Date(year, 3, 21), 'Tiradentes', 'holiday'], [new Date(year, 4, 1), 'Dia do Trabalho', 'holiday'],
      [nthSunday(year, 4, 2), 'Dia das Mães', 'date'], [addDays(e, 60), 'Corpus Christi', 'holiday'], [new Date(year, 5, 12), 'Dia dos Namorados', 'date'],
      [new Date(year, 6, 26), 'Dia dos Avós', 'date'], [nthSunday(year, 7, 2), 'Dia dos Pais', 'date'], [new Date(year, 8, 7), 'Independência do Brasil', 'holiday'],
      [new Date(year, 9, 1), 'Dia da Pessoa Idosa', 'date'], [new Date(year, 9, 12), 'Nossa Sra. Aparecida e Dia das Crianças', 'holiday'], [new Date(year, 10, 2), 'Finados', 'holiday'],
      [new Date(year, 10, 15), 'Proclamação da República', 'holiday'], [new Date(year, 10, 20), 'Consciência Negra', 'holiday'], [new Date(year, 11, 25), 'Natal', 'holiday']];
    return list.map(([date, name, kind]) => ({date, name, kind}));
  }
  let calendarKey = '';
  function renderCalendar() {
    const box = $('calendar'), now = new Date(), bdays = last.bdays || [];
    box.classList.toggle('hidden', !cfg().calendar);
    const key = `${now.toDateString()}|${JSON.stringify(bdays)}|${cfg().calendar}`;
    if (key === calendarKey) return;
    calendarKey = key;
    const year = now.getFullYear(), month = now.getMonth();
    const events = [...specialDays(year), ...specialDays(year + 1)];
    for (const y of [year, year + 1]) for (const b of bdays) { const [m, d] = b.d.split('-').map(Number); events.push({date: new Date(y, m - 1, d), name: `Aniversário de ${b.n}`, kind: 'bday'}); }
    const on = date => events.filter(ev => ev.date.getFullYear() === date.getFullYear() && ev.date.getMonth() === date.getMonth() && ev.date.getDate() === date.getDate());
    const first = new Date(year, month, 1), days = new Date(year, month + 1, 0).getDate();
    let cells = ['D', 'S', 'T', 'Q', 'Q', 'S', 'S'].map(l => `<b>${l}</b>`).join('') + '<span class="cal-day out"></span>'.repeat(first.getDay());
    for (let day = 1; day <= days; day++) {
      const found = on(new Date(year, month, day)), kinds = ['holiday', 'bday', 'date'].filter(k => found.some(ev => ev.kind === k));
      cells += `<span class="cal-day ${kinds[0] || ''} ${day === now.getDate() ? 'today' : ''}">${day}</span>`;
    }
    const today = new Date(year, month, now.getDate());
    const upcoming = events.filter(ev => ev.date >= today).sort((a, b) => a.date - b.date).slice(0, 4).map(ev => {
      const diff = Math.round((ev.date - today) / 86400000), when = diff === 0 ? 'Hoje' : diff === 1 ? 'Amanhã' : `Em ${diff} dias`;
      return `<li><span class="when">${when}</span> <b>${ev.kind === 'bday' ? '🎂 ' : ''}${ev.name.replace(/</g, '&lt;')}</b></li>`;
    }).join('');
    box.innerHTML = `<div class="cal-title"><span>${now.toLocaleDateString('pt-BR', {month: 'long'})}</span><small>${year}</small></div><div class="cal-grid">${cells}</div><ul class="cal-next">${upcoming}</ul>`;
  }

  // The family member's camera arrives through MediaMTX ("face"); until it does, the initial letter shows.
  function watchFace(on) {
    if (!on) {
      clearTimeout(faceTimer); faceTimer = null;
      if (face) { face.close(); face = null; }
      $('face').srcObject = null; $('face').classList.add('hidden'); $('avatar').classList.remove('hidden');
      return;
    }
    if (face || faceTimer) return;
    faceTimer = setTimeout(async () => {
      faceTimer = null;
      const pc = new RTCPeerConnection();
      face = pc;
      pc.addTransceiver('video', {direction: 'recvonly'});
      pc.ontrack = event => {
        $('face').srcObject = event.streams[0] || new MediaStream([event.track]);
        $('face').classList.remove('hidden'); $('avatar').classList.add('hidden');
      };
      pc.onconnectionstatechange = () => {
        if (['failed', 'closed', 'disconnected'].includes(pc.connectionState) && face === pc) { watchFace(false); if (screen.dataset.view === 'answered') watchFace(true); }
      };
      try {
        await pc.setLocalDescription(await pc.createOffer());
        await new Promise(resolve => { pc.onicegatheringstatechange = () => pc.iceGatheringState === 'complete' && resolve(); setTimeout(resolve, 1000); });
        const response = await fetch('http://127.0.0.1:8889/face/whep', {method: 'POST', headers: {'Content-Type': 'application/sdp'}, body: pc.localDescription.sdp});
        if (response.status !== 201) throw new Error('sem vídeo ainda');
        await pc.setRemoteDescription({type: 'answer', sdp: await response.text()});
      } catch {
        // Nobody publishing yet (or no camera on their side): try again shortly.
        if (face === pc) { watchFace(false); if (screen.dataset.view === 'answered') faceTimer = setTimeout(() => { faceTimer = null; watchFace(true); }, 2500); }
      }
    }, 0);
  }

  async function poll() {
    try { last = await (await fetch('/state', {cache: 'no-store'})).json(); }
    catch { last = {call: {state: 'idle'}, linked: false, enabled: {call: false, panic: false}}; }
    render();
  }

  clock(); setInterval(clock, 10000);
  poll(); setInterval(poll, 1000);
})();
