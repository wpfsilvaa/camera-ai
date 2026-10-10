// Tela do notebook da cozinha: botões grandes para chamar a família e o rosto de quem atendeu.
(() => {
  const $ = id => document.getElementById(id);
  const screen = $('screen');
  let last = {call: {state: 'idle'}}, confirming = false, face = null, faceTimer = null;
  let build = null, greetedId = null, greetTimer = null;
  const VIGIA = {off: 'Vigia desativado', resting: 'Vigia ativo', analysing: 'Vigia analisando', scheduled: 'Vigia agendado'};

  const post = path => fetch(path, {method: 'POST', headers: {'X-Kiosk': '1', 'Content-Type': 'application/json'}, body: '{}'});

  async function press(kind) {
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
    document.documentElement.dataset.night = last.night ? '1' : '0';
    const state = VIGIA[last.vigia] ? last.vigia : '';
    screen.dataset.vigia = state;
    $('vigia').classList.toggle('hidden', !state);
    $('vigia-text').textContent = VIGIA[state] || '';
    document.querySelector('.vi-shield').classList.toggle('hidden', state === 'analysing');
    document.querySelector('.vi-eye').classList.toggle('hidden', state !== 'analysing');
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
    const box = $('greeting'), sub = $('greeting-sub');
    const hide = () => { box.classList.add('hidden'); sub.classList.add('hidden'); $('confetti').classList.add('hidden'); $('confetti').innerHTML = ''; };
    if (view !== 'idle') { hide(); return; }
    if (last.greet && last.greet.id !== greetedId) {
      greetedId = last.greet.id;
      const hour = new Date().getHours(), period = hour >= 5 && hour < 12 ? 'Bom dia' : hour >= 12 && hour < 18 ? 'Boa tarde' : 'Boa noite', birthday = !!last.greet.birthday;
      box.textContent = birthday ? `🎂 Feliz aniversário, ${last.greet.name}!` : `${period}, ${last.greet.name}`;
      box.classList.toggle('birthday', birthday);
      box.classList.remove('hidden');
      sub.textContent = birthday ? `${last.greet.age ? `Hoje você completa ${last.greet.age} anos. ` : ''}${BIRTHDAY_LINES[last.greet.id % BIRTHDAY_LINES.length]}` : '';
      sub.classList.toggle('hidden', !birthday);
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
    if (!items.length) { remKey = ''; return; }
    remIndex %= items.length;
    const item = items[remIndex], key = `${item.i}:${remIndex}:${items.length}`;
    if (key === remKey) return;
    remKey = key;
    $('rem-text').textContent = item.t;
    const until = new Date(item.e * 1000), same = until.toDateString() === new Date().toDateString();
    $('rem-meta').textContent = `${item.a ? `${item.a} · ` : ''}até ${same ? '' : until.toLocaleDateString('pt-BR', {weekday: 'short', day: 'numeric'}) + ' '}${until.toLocaleTimeString('pt-BR', {hour: '2-digit', minute: '2-digit'})}`;
    $('rem-dots').innerHTML = items.length > 1 ? items.map((_, i) => `<i class="${i === remIndex ? 'on' : ''}"></i>`).join('') : '';
  }
  setInterval(() => { if ((last.reminders || []).length > 1) { remIndex++; renderReminder(); } }, 9000);

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
    const key = `${now.toDateString()}|${JSON.stringify(bdays)}`;
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
