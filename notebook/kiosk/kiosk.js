// Tela do notebook da cozinha: botões grandes para chamar a família e o rosto de quem atendeu.
(() => {
  const $ = id => document.getElementById(id);
  const screen = $('screen');
  let last = {call: {state: 'idle'}}, confirming = false, face = null, faceTimer = null;
  let build = null, greetedId = null, greetTimer = null;
  const DEFAULT_CFG = {slide: 15, awake: 30, sound: true, vol: {button: 70, call: 70, help: 100, message: 80}, calendar: true, framecal: 'always', hints: [], black: true};
  const cfg = () => ({...DEFAULT_CFG, ...(last.cfg || {}), vol: {...DEFAULT_CFG.vol, ...((last.cfg || {}).vol || {})}});

  // Sounds generated here (no files). Each kind has its own volume (0-100, set for day and night in the dashboard);
  // a test from the dashboard plays at the slider's value even before it is saved.
  let audio = null, ringTimer = null, shownView = 'idle', testVolume = null;
  const level = name => (testVolume !== null ? testVolume : cfg().sound ? cfg().vol[name] : 0) / 100;
  function tone(freq, at, length, name, relative = 1) {
    const volume = 0.5 * level(name) * relative;
    if (volume <= 0.001) return;
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
  const sounds = {
    press: () => tone(660, 0, 0.12, 'button', 0.8),
    ring: kind => kind === 'panic'
      ? [0, 0.28, 0.56].forEach(at => tone(880, at, 0.18, 'help'))                      // Urgent: three quick high beeps.
      : [0, 0.55].forEach(at => tone(425, at, 0.4, 'call', 0.8)),                        // Calm "tu-tu" like a phone ringing.
    message: () => [[784, 0], [988, 0.2], [1175, 0.4]].forEach(([f, at]) => tone(f, at, 0.28, 'message')),   // Bright rising chime.
    answered: () => { tone(523, 0, 0.16, 'button', 0.8); tone(784, 0.18, 0.28, 'button', 0.8); },
    over: () => { tone(784, 0, 0.16, 'button', 0.7); tone(523, 0.18, 0.3, 'button', 0.7); },
  };
  // Sounds asked for by the dashboard ("Testar" buttons): played once, at the volume of the slider.
  const seenTests = new Set();
  function runTests() {
    for (const test of last.tests || []) {
      if (seenTests.has(test.id)) continue;
      seenTests.add(test.id);
      testVolume = test.volume;
      try {
        if (test.sound === 'press') sounds.press();
        else if (test.sound === 'ring') sounds.ring('call');
        else if (test.sound === 'help') sounds.ring('panic');
        else if (test.sound === 'message') showQuotes([{i: '', t: test.text || 'Esta é uma mensagem de teste.', a: 'Teste', vol: test.volume, ms: 8000}], 0, 'Mensagem de teste', false);
      } catch { /* no audio device */ }
      testVolume = null;
    }
  }
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
    await poll(true);
  }

  $('btn-call').onclick = () => press('call');
  $('btn-panic').onclick = () => { confirming = true; render(); };
  $('confirm-yes').onclick = () => press('panic');
  $('confirm-no').onclick = () => { confirming = false; render(); };
  $('btn-cancel').onclick = async () => { await post('/cancel'); poll(true); };
  $('btn-end').onclick = async () => { await post('/cancel'); poll(true); };

  function clock() {
    const now = new Date();
    $('clock').textContent = now.toLocaleTimeString('pt-BR', {hour: '2-digit', minute: '2-digit'});
    $('date').textContent = now.toLocaleDateString('pt-BR', {weekday: 'long', day: 'numeric', month: 'long'});
    $('frame-clock').textContent = $('clock').textContent;
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
    runTests();
    renderFrameInfo();
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
  // Messages left for the person being greeted, one after the other, quote-style with the sender underneath.
  // Each message stays 20 s (or until the person taps "Li", which tells the family it was read).
  let quoteQueue = [], quoteTimer = null, quoteId = '', chimeTimer = null;
  function hideQuote() { clearTimeout(quoteTimer); clearTimeout(chimeTimer); quoteQueue = []; quoteId = ''; $('quote').classList.add('hidden'); syncSpeaking(); }
  function nextQuote() {
    clearTimeout(quoteTimer);
    const item = quoteQueue.shift();
    if (!item) { quoteId = ''; $('quote').classList.add('hidden'); syncSpeaking(); return; }
    quoteId = item.i || '';
    $('quote-text').textContent = item.t; $('quote-by').textContent = item.a || '';
    const single = Boolean(item.s);
    $('quote-ok').classList.toggle('hidden', !quoteId || single);
    $('quote-timer').classList.toggle('hidden', !single);
    if (single) { const bar = $('quote-timer').querySelector('i'); bar.style.animation = 'none'; void bar.offsetWidth; bar.style.animation = ''; }
    // View-once: showing it is what consumes it, so the screen tells the dashboard right away.
    if (single && quoteId) fetch('/ack', {method: 'POST', headers: {'X-Kiosk': '1', 'Content-Type': 'application/json'}, body: JSON.stringify({id: quoteId})}).catch(() => {});
    const head = $('quote-head');
    head.textContent = quoteHead.text; head.classList.toggle('hidden', !quoteHead.text); head.classList.toggle('birthday', quoteHead.birthday);
    head.classList.remove('rise'); if (quoteHead.fresh) { void head.offsetWidth; head.classList.add('rise'); quoteHead.fresh = false; }   // Moves up once.
    $('quote').classList.remove('hidden'); $('quote').style.animation = 'none'; void $('quote').offsetWidth; $('quote').style.animation = '';
    syncSpeaking();
    quoteTimer = setTimeout(nextQuote, item.ms || (single ? 30000 : 20000));
    testVolume = item.vol ?? null;
    try { sounds.message(); } catch { /* no audio device */ }
    testVolume = null;
    $('quote').classList.remove('attn'); void $('quote').offsetWidth; $('quote').classList.add('attn');
    clearTimeout(chimeTimer);
    const current = quoteId;
    chimeTimer = setTimeout(() => { if (current && !item.vol && !single && quoteId === current) { try { sounds.message(); } catch { /* ignore */ } } }, 9000);   // Still unread: once more.
  }
  let quoteHead = {text: '', birthday: false, fresh: false};
  function showQuotes(items, delay, headline = '', birthday = false) {
    hideQuote(); quoteQueue = [...items]; quoteHead = {text: headline, birthday, fresh: Boolean(headline)};
    quoteTimer = setTimeout(nextQuote, delay);
  }
  $('quote-ok').onclick = async () => {
    try { sounds.press(); } catch { /* ignore */ }
    if (quoteId) await fetch('/ack', {method: 'POST', headers: {'X-Kiosk': '1', 'Content-Type': 'application/json'}, body: JSON.stringify({id: quoteId})}).catch(() => {});
    nextQuote();
  };
  const syncSpeaking = () => $('frame').classList.toggle('speaking', !$('quote').classList.contains('hidden') || !$('frame-greeting').classList.contains('hidden'));

  function greet(view) {
    const pairs = [['greeting', 'greeting-sub'], ['frame-greeting', 'frame-greeting-sub']];
    const hide = () => { pairs.flat().forEach(id => $(id).classList.add('hidden')); $('confetti').classList.add('hidden'); $('confetti').innerHTML = ''; syncSpeaking(); };
    if (view !== 'idle') { hide(); hideQuote(); return; }
    if (last.greet && last.greet.id !== greetedId) {
      greetedId = last.greet.id;
      const msgs = last.greet.msgs || [], birthday = !!last.greet.birthday, shownFor = birthday ? 25000 : 10000;
      if (!last.greet.quiet) {
        const hour = new Date().getHours(), period = hour >= 5 && hour < 12 ? 'Bom dia' : hour >= 12 && hour < 18 ? 'Boa tarde' : 'Boa noite';
        const text = birthday ? `🎂 Feliz aniversário, ${last.greet.name}!` : `${period}, ${last.greet.name}`;
        const extra = birthday ? `${last.greet.age ? `Hoje você completa ${last.greet.age} anos. ` : ''}${BIRTHDAY_LINES[last.greet.id % BIRTHDAY_LINES.length]}` : '';
        if (msgs.length) {
          // A message is waiting: no big greeting first, the greeting sits on top of the message card straight away.
          pairs.flat().forEach(id => $(id).classList.add('hidden'));
          if (birthday) party(); else $('confetti').classList.add('hidden');
          clearTimeout(greetTimer);
          if (birthday) greetTimer = setTimeout(() => { $('confetti').classList.add('hidden'); $('confetti').innerHTML = ''; }, shownFor);
          showQuotes(msgs, 0, text, birthday);
        } else {
          for (const [headline, sub] of pairs) {
            $(headline).textContent = text; $(headline).classList.toggle('birthday', birthday); $(headline).classList.remove('hidden');
            $(sub).textContent = extra; $(sub).classList.toggle('hidden', !birthday);
          }
          if (birthday) party(); else $('confetti').classList.add('hidden');
          clearTimeout(greetTimer);
          greetTimer = setTimeout(hide, shownFor);
          syncSpeaking();
        }
      } else if (msgs.length) showQuotes(msgs, 0);
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

  // Photo frame information: date, "today" line, week strip and the small status pills.
  const ICON_SHIELD = '<svg class="vi" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.5 4.5 5.5v6c0 4.6 3.1 8.4 7.5 10 4.4-1.6 7.5-5.4 7.5-10v-6L12 2.5Z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="m8.7 12.2 2.4 2.4 4.3-4.6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  const ICON_EYE = '<svg class="vi" viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12Z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><circle cx="12" cy="12" r="3" fill="currentColor"/></svg>';
  let infoKey = '';
  function renderFrameInfo() {
    const now = new Date(), bdays = last.bdays || [], events = allEvents(bdays);
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()), tomorrow = addDays(today, 1);
    const names = date => eventsOn(events, date).map(ev => ev.name.replace(/</g, '&lt;'));
    const hour = now.getHours(), period = hour >= 5 && hour < 12 ? 'Bom dia' : hour >= 12 && hour < 18 ? 'Boa tarde' : 'Boa noite';
    const todayLine = names(today).length ? `Hoje: ${names(today).join(' · ')}` : names(tomorrow).length ? `Amanhã: ${names(tomorrow).join(' · ')}` : period;
    const battery = last.battery != null && (last.plugged === false || last.battery < 20) ? `<span class="fr-pill low">🔋 ${last.battery}%${last.plugged === false ? ' sem carregador' : ''}</span>` : '';
    const vigia = VIGIA[last.vigia] ? `<span class="fr-pill ${last.vigia}">${last.vigia === 'analysing' ? ICON_EYE : ICON_SHIELD}${VIGIA[last.vigia]}</span>` : '';
    const key = `${now.toDateString()}|${now.getHours()}|${todayLine}|${last.vigia}|${battery}|${JSON.stringify(bdays)}`;
    if (key === infoKey) return;
    infoKey = key;
    const dateText = now.toLocaleDateString('pt-BR', {weekday: 'long', day: 'numeric', month: 'long'});
    $('frame-date').textContent = dateText.charAt(0).toUpperCase() + dateText.slice(1);
    $('frame-today').textContent = todayLine.replace(/&lt;/g, '<');
    $('frame-status').innerHTML = vigia + battery;
  }

  // Photo frame --------------------------------------------------------------
  // By day an idle screen shows the family photos; at night it is black. Touch, mouse or key brings the buttons back.
  let slideMs = 0, monthTimer = null, monthFirst = null, monthPopping = false;
  let awakeUntil = 0, swallowClick = false, order = [], active = 'a', slideTimer = null, hintTimer = null, hintIndex = 0, lastMove = 0;

  function wake() { awakeUntil = Date.now() + cfg().awake * 1000; render(); }
  document.addEventListener('pointerdown', event => {
    if (screen.dataset.mode !== 'ui' && $('quote').classList.contains('hidden')) { swallowClick = true; event.preventDefault(); event.stopPropagation(); }
    wake();
  }, true);
  document.addEventListener('click', event => { if (swallowClick) { swallowClick = false; event.preventDefault(); event.stopPropagation(); } }, true);
  document.addEventListener('keydown', wake, true);
  document.addEventListener('pointermove', event => { if (Date.now() - lastMove > 500 && (Math.abs(event.movementX) + Math.abs(event.movementY) > 3)) { lastMove = Date.now(); wake(); } }, true);

  // Picks white or dark text for the top-left and bottom areas depending on how bright the photo is there.
  function toneFor(img) {
    try {
      const W = innerWidth, H = innerHeight, scale = Math.min(W / img.naturalWidth, H / img.naturalHeight), dw = img.naturalWidth * scale, dh = img.naturalHeight * scale;
      const ox = (W - dw) / 2, oy = (H - dh) / 2, canvas = document.createElement('canvas');
      canvas.width = 64; canvas.height = 36;
      const g = canvas.getContext('2d', {willReadFrequently: true});
      g.drawImage(img, 0, 0, 64, 36);
      const brightness = (x0, y0, x1, y1) => {
        let sum = 0, n = 0;
        for (let sx = x0; sx < x1; sx += (x1 - x0) / 14) for (let sy = y0; sy < y1; sy += (y1 - y0) / 6) {
          n++;
          if (sx < ox || sx > ox + dw || sy < oy || sy > oy + dh) { sum += 0.15; continue; }   // Letterbox: the dark blurred copy.
          const d = g.getImageData(Math.min(63, Math.floor((sx - ox) / dw * 64)), Math.min(35, Math.floor((sy - oy) / dh * 36)), 1, 1).data;
          sum += (0.2126 * d[0] + 0.7152 * d[1] + 0.0722 * d[2]) / 255;
        }
        return sum / n;
      };
      return {top: brightness(0, 0, W * 0.5, H * 0.3), bottom: brightness(0, H * 0.68, W, H)};
    } catch { return {top: 0, bottom: 0}; }
  }
  function applyTone(tone) {
    const frame = $('frame');
    const set = (zone, bright) => {
      frame.style.setProperty(`--fg-${zone}`, bright ? '#14181a' : '#fff');
      frame.style.setProperty(`--sh-${zone}`, bright ? '0 .1vmin 1.2vmin #fffc' : '0 .15vmin 1.6vmin #000c');
      frame.style.setProperty(`--scrim-${zone === 'top' ? 'top' : 'bot'}`, bright ? 'transparent' : (zone === 'top' ? '#0008' : '#000a'));
    };
    set('top', tone.top > 0.62); set('bot', tone.bottom > 0.62);
  }

  let creditTimer = null;
  function nextSlide() {
    const photos = last.photos || [], ids = photos.map(p => p.id);
    if (!ids.length) return;
    order = order.filter(id => ids.includes(id));
    if (!order.length) order = [...ids].sort(() => Math.random() - 0.5);
    const id = order.shift(), who = (photos.find(p => p.id === id) || {}).a, incoming = active === 'a' ? 'b' : 'a', el = $('slide-' + incoming), outgoing = $('slide-' + active), img = el.querySelector('img');
    img.onload = () => {
      el.querySelector('.back').style.backgroundImage = `url(/photo/${id}.jpg)`;
      img.style.setProperty('--kb', `${30 + Math.random() * 40}% ${30 + Math.random() * 40}%`);
      el.classList.remove('leaving'); el.classList.add('on');
      outgoing.classList.remove('on'); outgoing.classList.add('leaving');
      setTimeout(() => outgoing.classList.remove('leaving'), 1800);
      active = incoming;
      applyTone(toneFor(img));
      const credit = $('frame-credit');
      credit.textContent = who ? `foto de ${who}` : '';
      credit.classList.toggle('on', Boolean(who));
      clearTimeout(creditTimer); creditTimer = setTimeout(() => credit.classList.remove('on'), 6000);
      const bar = $('frame-progress');
      bar.classList.remove('run'); void bar.offsetWidth; bar.style.setProperty('--slide', `${cfg().slide}s`); bar.classList.add('run');
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
    for (const b of last.bdays || []) {
      const [m, d] = b.d.split('-').map(Number), diff = Math.round((new Date(today.getFullYear(), m - 1, d) - today) / 86400000);
      if (diff >= 2 && diff <= 7) list.push(`🎂 Faltam ${diff} dias para o aniversário de ${b.n}`);
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
      const month = $('frame-cal'), pop = () => { if (cfg().framecal !== 'pulse') return; monthPopping = true; month.classList.add('show'); setTimeout(() => { monthPopping = false; month.classList.remove('show'); }, 12000); };
      monthTimer = setInterval(pop, 60000); monthFirst = setTimeout(pop, 5000);
    } else if (!on && slideTimer) {
      clearInterval(slideTimer); clearInterval(hintTimer); clearInterval(monthTimer); clearTimeout(monthFirst); slideTimer = hintTimer = null;
      $('frame-cal').classList.remove('show');
    }
  }

  function applyMode(view) {
    const awake = Date.now() < awakeUntil, photos = (last.photos || []).map(p => p.id);
    let mode = 'ui';
    if (view === 'idle' && last.frame && !awake) mode = last.night && cfg().black ? 'black' : photos.length ? 'frame' : 'ui';
    if (slideTimer && slideMs !== cfg().slide * 1000) startFrame(false);   // The interval changed in the settings.
    screen.dataset.mode = mode;
    $('frame').classList.toggle('hidden', mode !== 'frame');
    // Month card on the frame: always there, sliding in for 12 s each minute, or never.
    const month = $('frame-cal'), how = cfg().framecal;
    if (mode === 'frame') month.classList.toggle('show', how === 'always' || (how === 'pulse' && monthPopping));
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
  // Events (holidays, special dates, birthdays) of this year and the next, for the calendar, the week strip and the "today" line.
  function allEvents(bdays) {
    const year = new Date().getFullYear(), events = [...specialDays(year), ...specialDays(year + 1)];
    for (const y of [year, year + 1]) for (const b of bdays) { const [m, d] = b.d.split('-').map(Number); events.push({date: new Date(y, m - 1, d), name: `Aniversário de ${b.n}`, kind: 'bday'}); }
    return events;
  }
  const eventsOn = (events, date) => events.filter(ev => ev.date.getFullYear() === date.getFullYear() && ev.date.getMonth() === date.getMonth() && ev.date.getDate() === date.getDate());

  function monthHTML(now, bdays) {
    const year = now.getFullYear(), month = now.getMonth(), events = allEvents(bdays);
    const first = new Date(year, month, 1), days = new Date(year, month + 1, 0).getDate();
    let cells = ['D', 'S', 'T', 'Q', 'Q', 'S', 'S'].map(l => `<b>${l}</b>`).join('') + '<span class="cal-day out"></span>'.repeat(first.getDay());
    for (let day = 1; day <= days; day++) {
      const found = eventsOn(events, new Date(year, month, day)), kinds = ['holiday', 'bday', 'date'].filter(k => found.some(ev => ev.kind === k));
      cells += `<span class="cal-day ${kinds[0] || ''} ${day === now.getDate() ? 'today' : ''}">${day}</span>`;
    }
    const today = new Date(year, month, now.getDate());
    const upcoming = events.filter(ev => ev.date >= today).sort((a, b) => a.date - b.date).slice(0, 4).map(ev => {
      const diff = Math.round((ev.date - today) / 86400000), when = diff === 0 ? 'Hoje' : diff === 1 ? 'Amanhã' : `Em ${diff} dias`;
      return `<li><span class="when">${when}</span> <b>${ev.kind === 'bday' ? '🎂 ' : ''}${ev.name.replace(/</g, '&lt;')}</b></li>`;
    }).join('');
    return `<div class="cal-title"><span>${now.toLocaleDateString('pt-BR', {month: 'long'})}</span><small>${year}</small></div><div class="cal-grid">${cells}</div><ul class="cal-next">${upcoming}</ul>`;
  }

  // Compact month for the photo frame: weeks other than the current one are dimmed, with the next events beside it.
  function miniMonthHTML(now, bdays) {
    const year = now.getFullYear(), month = now.getMonth(), events = allEvents(bdays), today = new Date(year, month, now.getDate());
    const first = new Date(year, month, 1), days = new Date(year, month + 1, 0).getDate(), weekStart = addDays(today, -today.getDay());
    let cells = ['D', 'S', 'T', 'Q', 'Q', 'S', 'S'].map(l => `<b>${l}</b>`).join('') + '<span class="mc-d out"></span>'.repeat(first.getDay());
    for (let day = 1; day <= days; day++) {
      const date = new Date(year, month, day), found = eventsOn(events, date), kind = ['holiday', 'bday', 'date'].find(k => found.some(ev => ev.kind === k));
      const inWeek = date >= weekStart && date < addDays(weekStart, 7);
      cells += `<span class="mc-d ${kind || ''} ${inWeek ? 'wk' : ''} ${day === now.getDate() ? 'today' : ''}">${day}</span>`;
    }
    const upcoming = events.filter(ev => ev.date >= today).sort((a, b) => a.date - b.date).slice(0, 3).map(ev => {
      const diff = Math.round((ev.date - today) / 86400000), when = diff === 0 ? 'Hoje' : diff === 1 ? 'Amanhã' : `Em ${diff} dias`;
      return `<li><span>${when}</span><b>${ev.kind === 'bday' ? '🎂 ' : ''}${ev.name.replace(/</g, '&lt;')}</b></li>`;
    }).join('');
    return `<div class="mc-grid"><div class="mc-title">${now.toLocaleDateString('pt-BR', {month: 'long'})}<small>${year}</small></div>${cells}</div><ul class="mc-next">${upcoming}</ul>`;
  }

  let calendarKey = '';
  function renderCalendar() {
    const box = $('calendar'), now = new Date(), bdays = last.bdays || [];
    box.classList.toggle('hidden', !cfg().calendar);
    const key = `${now.toDateString()}|${JSON.stringify(bdays)}|${cfg().calendar}`;
    if (key === calendarKey) return;
    calendarKey = key;
    const html = monthHTML(now, bdays);
    box.innerHTML = html;
    $('frame-cal').innerHTML = miniMonthHTML(now, bdays);
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

  // The monitor answers /state at once when something changes (long-poll) and at least every 3 s; `version` says what we have.
  let version = -1;
  const OFFLINE = {call: {state: 'idle'}, linked: false, enabled: {call: false, panic: false}};
  async function poll(immediate = false) {
    try {
      const response = await fetch(immediate ? '/state' : `/state?v=${version}&wait=3`, {cache: 'no-store'});
      const data = await response.json();
      if (!immediate || data.v !== undefined) version = data.v ?? version;
      last = data;
    } catch { last = OFFLINE; await new Promise(resolve => setTimeout(resolve, 1000)); }
    render();
  }

  clock(); setInterval(clock, 10000);
  (async () => { for (;;) await poll(); })();   // Waits for changes instead of asking every second.
  setInterval(render, 1000);                      // Timers on the screen (greetings, wake-up) still advance locally.
})();
