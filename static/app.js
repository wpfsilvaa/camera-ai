const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const escapeHTML = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const date = (seconds, opts = {}) => seconds ? new Date(seconds * 1000).toLocaleString('pt-BR', {timeZone:'America/Sao_Paulo', ...opts}) : '—';
const time = (seconds) => date(seconds, {hour:'2-digit',minute:'2-digit'});
const day = (seconds) => date(seconds, {day:'2-digit',month:'short'});
const duration = (seconds) => seconds < 60 ? `${Math.max(0, Math.round(seconds))} s` : `${Math.floor(seconds / 60)} min ${Math.round(seconds % 60)} s`;
const identity = {father:['Meu pai','green'], unknown:['A identificar','amber'], other:['Outra pessoa','neutral']};
const delivery = {pending:'Na fila', sending:'Enviando…', sent:'Enviado', retry:'Nova tentativa', failed:'Falha no envio', uncertain:'Conferir envio'};
let settings, status, activePage = 'overview', historyFilter = 'all', offset = 0, total = 0;
let recentEvents = [], historyEvents = [], selectedEvent, streamActive = false, toastTimer, polling = false;
let profiles = [];
let selectedCamera = 'main', historyCamera = '', knownCameras = [];
const cameraPath = path => `${path}${path.includes('?')?'&':'?'}camera_id=${encodeURIComponent(selectedCamera)}`;

function personSummary(event) {
  const names = [...new Set((event.people || []).map(t => t.reviewed ? t.name : t.suggested_name ? `Provável ${t.suggested_name}${t.recognition_kind==='body'?' (corpo/roupa)':''}` : null).filter(Boolean))];
  return names.length ? names.join(' · ') : identity[event.identity][0];
}

function renderProfiles() {
  const recognition = status?.recognition;
  if (!recognition) return;
  profiles = recognition.profiles;
  $('#recognition-status').textContent = !settings.recognition_enabled ? 'Reconhecimento facial desativado nas configurações.' : recognition.error || (settings.body_reid_enabled && recognition.body_error) || (recognition.ready ? `Reconhecimento facial local ativo.${settings.body_reid_enabled ? ` Memória corporal: ${recognition.body_reference_people || 0} pessoa(s), por até ${settings.body_memory_minutes} minutos após reconhecer o rosto.` : ''} Cadastre fotos nítidas do rosto.` : 'O modelo facial será iniciado com a câmera ou ao cadastrar uma foto.');
  $('#people-profiles').innerHTML = profiles.map(person => `<article class="panel profile-card"><div class="profile-avatar">${escapeHTML(person.name.slice(0,1).toUpperCase())}</div><h2>${escapeHTML(person.name)}</h2><span class="pill ${person.examples>=1?'green':'amber'}">${person.examples>=1?'Pode receber sugestões':'Precisa de exemplos'}</span><p>${person.examples} rosto(s) cadastrado(s)</p><p class="small muted">Presença confirmada em ${person.records} registro(s)${person.is_father ? ' · Perfil do pai' : ''}</p><button type="button" class="button primary compact upload-face" data-face-upload="${person.id}">Cadastrar foto do rosto</button><div class="enrollment-photos">${(person.enrollments||[]).map(face=>`<div><img src="/people-media/${face.id}.jpg" alt="Rosto cadastrado de ${escapeHTML(person.name)}"><button class="text-button" data-remove-face="${face.id}" data-person="${person.id}">Remover</button></div>`).join('')}</div><div class="profile-actions"><button class="text-button" data-review-examples="${person.id}">Revisar exemplos (${person.examples})</button><button class="text-button" data-rename-person="${person.id}">Renomear</button><button class="text-button" data-forget-person="${person.id}">Esquecer exemplos</button>${!person.is_father?`<button class="text-button" data-delete-person="${person.id}">Excluir perfil</button>`:''}</div></article>`).join('');
}

function diagnosticHTML(track) {
  const d=track.diagnostic || {};
  const reasons={no_face:'Rosto não localizado: pode estar de costas, encoberto ou fora do enquadramento.',small_face:'Rosto pequeno demais para comparação. Aproxime ou ajuste o enquadramento.',small_person:'Pessoa pequena demais na imagem para extrair o rosto.',blurred_face:'Rosto descartado por pouca nitidez. Confira foco, movimento e iluminação.',multiple_faces:'Mais de um rosto no mesmo recorte; associação incerta.',ambiguous_owner:'O rosto pode pertencer a mais de uma pessoa detectada.',no_references:'Nenhum exemplo facial compatível disponível.',below_threshold:'A semelhança ficou abaixo do limite configurado.',ambiguous_match:'Os melhores candidatos ficaram próximos demais entre si.',waiting_agreement:'Aguardando três comparações concordantes.',matched:'Rosto reconhecido após comparações concordantes.',usable_face:'Rosto adequado para comparação.'};
  const message=reasons[d.reason] || 'Este registro antigo não possui diagnóstico facial.';
  const details=[d.face_pixels!=null?`Rosto: ${d.face_pixels} px`:null,d.sharpness!=null?`Nitidez: ${d.sharpness}`:null,d.score!=null?`Semelhança: ${Number(d.score).toFixed(2)} (limite ${Number(d.threshold).toFixed(2)})`:null,d.reason==='waiting_agreement'?`${d.agreement}/${d.required} comparações`:null].filter(Boolean);
  const b=d.body;
  const bodyReasons={continued_match:'Aparência consistente com a pessoa já acompanhada.',learning_view:'Guardando este ângulo pela continuidade do tracking após reconhecer o rosto.',no_references:'Sem memória corporal válida. É necessário reconhecer o rosto primeiro.',below_threshold:'A roupa/corpo ficou abaixo da semelhança mínima.',ambiguous_match:'A aparência combina com mais de uma pessoa.',waiting_agreement:'Aguardando três comparações corporais concordantes.',matched:'Aparência corporal reconhecida; identidade provável.',overlap:'Corpos sobrepostos: comparação e aprendizado suspensos.',small_body:'Corpo pequeno demais para comparar.',usable_body:'Corpo adequado para comparação.'};
  const bodyDetails=b?[b.score!=null?`Semelhança: ${Number(b.score).toFixed(2)} (limite ${Number(b.threshold).toFixed(2)})`:null,b.gap!=null?`Diferença entre candidatos: ${Number(b.gap).toFixed(2)} (mínimo ${Number(b.margin).toFixed(2)})`:null,b.agreement!=null?`${b.agreement}/${b.required} comparações`:null].filter(Boolean):[];
  const bodyHTML=b?`<strong>Última avaliação do corpo/roupa</strong><p>${escapeHTML(bodyReasons[b.reason] || 'Comparação corporal indisponível.')}</p>${bodyDetails.length?`<small>${escapeHTML(bodyDetails.join(' · '))}</small>`:''}`:'';
  return `<div class="inline-note recognition-diagnostic"><strong>Última avaliação do rosto</strong><p>${escapeHTML(message)}</p>${details.length?`<small>${escapeHTML(details.join(' · '))}</small>`:''}${bodyHTML}</div>`;
}

function personTracksHTML(event) {
  return `<h3>Quem aparece aqui?</h3><p>Escolha um rosto nítido e confirme o nome de cada pessoa. Apenas o rosto selecionado será usado como exemplo. Você pode confirmar outras imagens depois.</p>${!event.ended?'<p class="pill amber">Aguarde o fim do registro para confirmar. Use “Atualizar registro” quando terminar.</p>':''}<div class="person-tracks">${event.people.map((track,index) => `<section class="person-track" data-track="${track.id}"><div class="track-heading"><strong>Pessoa ${index+1} · #${track.track_key}</strong><span class="pill ${track.reviewed?'green':track.suggested_name?'amber':'neutral'}">${escapeHTML(track.reviewed ? track.name : track.suggested_name ? `Provável ${track.suggested_name}${track.recognition_kind==='body'?' (corpo/roupa)':''}` : 'Desconhecido')}</span></div>${diagnosticHTML(track)}<div class="sample-strip">${track.samples.map((sample,i) => `<label class="sample-choice"><input type="radio" name="sample-${track.id}" value="${sample.id}" ${i===0?'checked':''}><img src="/people-media/${sample.id}.jpg" alt="Imagem ${i+1} da pessoa ${index+1}" loading="lazy"><small>${time(sample.created)} · nitidez ${Math.round(sample.quality)}${i===0?' · mais nítida':''}${sample.person_id?' · ensinada':''}</small></label>`).join('') || '<p class="muted small">Sem rosto nítido suficiente para reconhecer. Você pode confirmar a presença após rever o vídeo, sem adicionar um exemplo.</p>'}</div>${track.suggested_name?`<p class="small muted">Semelhança ${Number(track.similarity).toFixed(2)} · estimativa, não certeza.</p>`:''}<div class="track-confirm"><label>Nome<select data-track-person="${track.id}" aria-label="Nome da pessoa ${index+1}"><option value="">Escolha uma pessoa</option>${profiles.map(p=>`<option value="${p.id}" ${track.person_id===p.id?'selected':''}>${escapeHTML(p.name)}</option>`).join('')}</select></label><button class="button primary compact" data-confirm-track="${track.id}" ${event.ended?'':'disabled'}>Confirmar${track.samples.length?' e ensinar':''}</button><button class="text-button" data-clear-track="${track.id}" ${event.ended?'':'disabled'}>Não sei / desfazer</button></div></section>`).join('')}</div><div class="track-footer"><button class="button secondary compact" data-refresh-event="${event.id}">Atualizar registro ↻</button><button class="text-button" data-new-person>+ Cadastrar outra pessoa</button></div><p class="small muted">Se um mesmo número misturar pessoas diferentes, confirme somente uma imagem que você reconheça. O rastreamento pode trocar números quando pessoas se cruzam.</p>`;
}

async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers:{'Content-Type':'application/json','X-Casa-Request':'1',...options.headers}, signal:options.signal || AbortSignal.timeout(12000)});
  let body;
  try { body = await response.json(); } catch { body = {}; }
  if (!response.ok) {
    const detail = Array.isArray(body.detail) ? body.detail.map(item => item.msg).join('; ') : body.detail;
    const error=new Error(detail || 'Não foi possível concluir a operação.');
    error.status=response.status;
    throw error;
  }
  return body;
}
function toast(message, error = false) {
  clearTimeout(toastTimer); $('#toast').textContent = message;
  $('#toast').className = `toast${error ? ' error' : ''}`;
  toastTimer = setTimeout(() => $('#toast').classList.add('hidden'), 5500);
}
async function action(button, fn) {
  button.disabled = true;
  try { await fn(); } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
}
function badge(kind) { const [text, color] = identity[kind] || identity.unknown; return `<span class="pill ${color}">${text}</span>`; }
function deliveryLabel(clip, event) {
  if (clip.state === 'expired') return 'Prazo de armazenamento encerrado';
  if (clip.state === 'failed') return 'Falha na gravação';
  if (clip.state === 'recording') return 'Gravando…';
  if (clip.state === 'processing') return 'Preparando vídeo…';
  if (clip.delivery === 'pending') {
    if(event.kind==='manual' && (event.analysis_state==='running' || event.identity==='unknown')) return 'Aguardando revisão';
    if (settings?.father_only && event.identity !== 'father' && !(settings.recognition_enabled && settings.send_probable_father && (event.people || []).some(t=>t.suggested_is_father && t.recognition_kind==='face' && !t.reviewed))) return 'Aguardando identificação';
    if (!settings?.whatsapp_enabled || !settings?.recipient) return 'Envio desativado';
  }
  return delivery[clip.delivery] || clip.delivery;
}
function fillSettings() {
  const form = $('#settings-form');
  for (const [name, value] of Object.entries(settings)) {
    const field = form.elements.namedItem(name);
    if (!field) continue;
    if (field.type === 'checkbox') field.checked = value;
    else {
      if (field.tagName === 'SELECT' && ![...field.options].some(option => option.value === String(value))) field.add(new Option(name==='confidence'?`${Math.round(value * 100)}%`:String(value), value));
      field.value = value;
    }
  }
}
function route() {
  const requested = location.hash.slice(1) || 'overview';
  activePage = ['overview','history','people','settings'].includes(requested) ? requested : 'overview';
  $$('.page').forEach(page => page.classList.toggle('hidden', page.id !== `page-${activePage}`));
  $$('.nav-link').forEach(link => link.classList.toggle('active', link.dataset.page === activePage));
  $('#page-name').textContent = {overview:'Visão geral',history:'Histórico',people:'Pessoas',settings:'Configurações'}[activePage];
  if (activePage === 'history') {loadHistory().catch(error => toast(error.message, true));loadHistoryCameras().catch(error=>toast(error.message,true));}
  if (activePage === 'people') renderProfiles();
  updateStream();
  if(status) renderCameraList();
}
$$('[data-go]').forEach(button => button.addEventListener('click', () => { location.hash = button.dataset.go; }));
window.addEventListener('hashchange', route);

function renderStatus() {
  const {camera, whatsapp, stats} = status;
  $('#father-count').textContent = stats.today.father;
  $('#unknown-count').textContent = stats.today.unknown;
  $('#nav-count').textContent = stats.today.unknown;
  $('#recorded-time').innerHTML = `${Math.floor(stats.recorded_seconds_today / 60)} <small>min</small>`;
  $('#sent-count').textContent = stats.sent_today;
  $('#pending-count').textContent = stats.pending ? `${stats.pending} vídeo(s) aguardando envio` : 'nenhum vídeo na fila';
  $('#camera-title').textContent = settings.camera_name;
  $('#live-image').alt = `Imagem ao vivo de ${settings.camera_name}`;
  $('#storage-info').textContent = `${status.storage_free_gb} GB livres · vídeos por ${settings.retention_days} dias`;
  const online = camera.state === 'online';
  const states = {paused:['Pausada','neutral'],connecting:['Conectando','amber'],online:['Ao vivo','green'],offline:['Sem sinal','red']};
  const [label, color] = states[camera.state] || states.offline;
  $('#camera-state').className = `pill ${color}`; $('#camera-state').textContent = label;
  $('#camera-health-dot').className = `dot${online ? '' : camera.state === 'offline' ? ' error' : ' gray'}`;
  $('#camera-placeholder').classList.toggle('hidden', online && streamActive);
  $('#live-image').classList.toggle('hidden', !online || !streamActive);
  $('#camera-placeholder-title').textContent = {paused:'Pronto para acompanhar',connecting:'Conectando à câmera…',offline:'Câmera indisponível',online:'Recebendo imagem…'}[camera.state] || 'Aguardando câmera';
  $('#camera-placeholder-description').textContent = camera.error || (camera.state === 'paused' ? 'Inicie a câmera para ver a imagem ao vivo.' : 'A imagem aparecerá aqui assim que estiver disponível.');
  $('#camera-footer').textContent = online && !camera.analysis_active ? `${camera.fps || 0} qps · somente vídeo` : online ? `${camera.fps || 0} qps vídeo · ${camera.detection_fps || 0} qps análise · ${camera.gpu || "CPU"} · ${camera.inference_ms} ms` : (camera.state === 'offline' ? 'Tentando restabelecer a conexão' : label);
  $('#people-count').textContent = online && !camera.analysis_active ? 'Análise pausada' : online ? `${camera.people} ${camera.people === 1 ? 'pessoa detectada' : 'pessoas detectadas'}` : 'Aguardando câmera';
  $('#recording-badge').classList.toggle('hidden', !camera.event_id && !camera.manual_recording);
  $('#toggle-analysis').textContent=settings.analysis_enabled ? 'Pausar análise' : 'Retomar análise';
  $('#analysis-note').textContent=camera.analysis_active ? 'Detecção e reconhecimento ativos.' : 'Somente vídeo: detecção de pessoas, reconhecimento e gravação por presença pausados.';
  $('#toggle-recording').textContent=camera.manual_requested || camera.manual_recording ? 'Parar gravação manual' : 'Gravar manualmente';
  $('#toggle-recording').disabled=!online && !camera.manual_requested && !camera.manual_recording;
  $('#offline-note').classList.toggle('hidden',!status.offline?.event_id);
  $('#offline-text').textContent=status.offline?.event_id ? `Analisando registro #${status.offline.event_id}. Essa tarefa usa processamento.` : '';
  $('#live-tag').textContent = online ? `AO VIVO · ${settings.camera_name.toUpperCase()}` : 'CÂMERA 01';
  $('#toggle-monitor').innerHTML = settings.enabled ? 'Pausar câmera <span>Ⅱ</span>' : 'Iniciar câmera <span>▶</span>';
  const connected = whatsapp.state === 'connected';
  $('#wa-dot').className = `dot${connected ? '' : ' gray'}`;
  $('#wa-title').textContent = connected ? 'WhatsApp conectado' : 'Os registros vão até você';
  $('#wa-description').textContent = connected ? (settings.whatsapp_enabled ? `Os vídeos ${settings.father_only ? 'confirmados como seu pai ' : ''}serão enviados para ${settings.recipient}.` : 'Agora configure o destinatário e ative os envios nas configurações.') : 'Conecte sua conta para receber os vídeos da câmera no WhatsApp.';
  const waLabel = {connected:'Conectado',disconnected:'Desconectado',connecting:'Conectando',qr:'Aguardando QR',unavailable:'Indisponível'}[whatsapp.state] || 'Desconectado';
  $('#wa-status').textContent = waLabel; $('#wa-status').className = `pill ${connected ? 'green' : 'neutral'}`;
  $('#connect-whatsapp').innerHTML = connected ? 'Configurar envio <span>↗</span>' : 'Conectar WhatsApp <span>↗</span>';
  if ($('#whatsapp-dialog').open) {
    $('#qr-image').classList.toggle('hidden', !whatsapp.qr);
    if (whatsapp.qr) $('#qr-image').src = whatsapp.qr;
    $('#qr-message').textContent = connected ? 'Conta conectada. Você já pode fechar esta janela.' : (whatsapp.error || (whatsapp.qr ? 'O código é atualizado automaticamente.' : 'Preparando conexão…'));
  }
  renderChart(stats.days);
  updateStream();
  $('#video-details').textContent = online ? `${camera.source_width}×${camera.source_height} · recebidos ${camera.input_fps ?? camera.source_fps} qps · declarados ${camera.source_fps} qps · atraso de processamento ${camera.frame_age_ms} ms${camera.half ? " · FP16" : ""}` : "Transmissão contínua · nomes incluídos nas gravações";
}
function renderChart(days) {
  $('#week-count').textContent = days.reduce((n, d) => n + d.total, 0);
  const max = Math.ceil(Math.max(4, ...days.map(d => d.total)) / 2) * 2;
  const plotHeight = 100, step = 50;
  let svg = `<svg viewBox="0 0 380 140" role="img" aria-label="Presenças por dia"><title>Presenças por dia: ${days.map(d => `${d.date}: ${d.total} registros, ${d.father} confirmados como pai`).join('; ')}</title>`;
  for (let i = 0; i <= 2; i++) svg += `<line class="grid" x1="23" y1="${10+i*50}" x2="378" y2="${10+i*50}"/><text x="3" y="${13+i*50}">${Math.round(max*(1-i/2))}</text>`;
  days.forEach((d,i) => {
    const x = 36+i*step, height = d.total/max*plotHeight, fatherHeight = d.father/max*plotHeight;
    svg += `<rect class="total-bar" x="${x}" y="${110-height}" width="26" height="${Math.max(height,2)}" rx="4"/><rect class="father-bar" x="${x}" y="${110-fatherHeight}" width="26" height="${fatherHeight}" rx="4"/><text x="${x+13}" y="133" text-anchor="middle">${d.date.slice(8)}/${d.date.slice(5,7)}</text>`;
  });
  $('#weekly-chart').innerHTML = svg + '</svg>';
}
function renderRecent() {
  if (!recentEvents.length) {
    $('#recent-list').innerHTML = '<div class="recent-empty"><span>◷</span><strong>Ainda sem registros por aqui</strong><p>Os próximos momentos de presença aparecerão aqui automaticamente.</p></div>'; return;
  }
  $('#recent-list').innerHTML = recentEvents.slice(0,3).map(event => {
    const clip = event.clips.find(c => !['expired','failed'].includes(c.state));
    return `<button class="recent-item" data-event="${event.id}">${clip ? `<img class="recent-thumb" src="/media/${clip.id}.jpg" alt="Prévia do registro" loading="lazy">` : '<span class="recent-thumb">◷</span>'}<span class="recent-info"><strong>${escapeHTML(identity[event.identity][0])}</strong><small>${escapeHTML(event.camera_name || 'Câmera principal')} · ${event.ended ? duration(event.ended-event.started) : 'Em andamento'}</small></span><span class="recent-time">${time(event.started)}<small>${day(event.started)}</small></span></button>`;
  }).join('');
}
async function loadHistory() {
  const requestedFilter = historyFilter, requestedOffset = offset, requestedCamera = historyCamera;
  const data = await api(`/api/events?limit=20&offset=${offset}&identity=${historyFilter}${historyCamera?`&camera_id=${encodeURIComponent(historyCamera)}`:''}`);
  if (requestedFilter !== historyFilter || requestedOffset !== offset || requestedCamera !== historyCamera) return;
  historyEvents = data.events; total = data.total;
  $('#history-total').textContent = `${total} registro(s)`;
  $('#history-empty').classList.toggle('hidden', Boolean(total));
  $('#history-table').innerHTML = historyEvents.map(event => `<tr><td><strong>${date(event.started,{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'})}</strong><small>${escapeHTML(event.camera_name || 'Câmera principal')} · #${event.id} · ${event.kind==='manual' ? 'Gravação manual' : `máximo ${event.max_people} pessoa(s)`}</small></td><td>${badge(event.identity)}</td><td>${event.ended ? duration(event.ended-event.started) : '<span class="pill green">Gravando</span>'}</td><td>${event.clips.length} parte(s)<small>${escapeHTML(event.clips.length ? deliveryLabel(event.clips.at(-1),event) : 'Preparando gravação')}</small></td><td><button class="button secondary compact" data-event="${event.id}">Revisar ↗</button></td></tr>`).join('');
  $('#previous-page').disabled = offset === 0;
  $('#next-page').disabled = offset + 20 >= total;
  $('#page-indicator').textContent = total ? `${offset+1}–${Math.min(offset+20,total)} de ${total}` : 'Nenhum registro';
  $$('#history-table tr').forEach((row,i) => { const small=document.createElement('small');small.textContent=personSummary(historyEvents[i]);row.children[1].append(small); });
}
function openEvent(event) {
  selectedEvent = event;
  $('#event-number').textContent = `${event.kind==='manual'?'GRAVAÇÃO MANUAL':'REGISTRO'} #${event.id} · ${event.camera_name || 'Câmera principal'}`;
  $('#event-title').textContent = date(event.started,{day:'2-digit',month:'long',hour:'2-digit',minute:'2-digit'});
  const reason = {manual_stopped:'Gravação encerrada por você',manual_started:'Gravação manual iniciada',analysis_paused:'Análise pausada; o vídeo ao vivo continuou',camera_error:'Encerrado por perda de sinal',interrupted:'Interrompido pelo reinício do sistema',settings_changed:'Encerrado ao pausar ou alterar a câmera',file_ended:'Fim do arquivo de vídeo',stopped:'Monitoramento encerrado'}[event.reason];
  $('#event-content').innerHTML = `<div class="event-meta">${badge(event.identity)}<span>${event.ended ? duration(event.ended-event.started) : 'Em andamento'}</span><span>${event.kind==='manual' && event.analysis_state!=='complete' ? 'Gravação manual · aguardando análise' : `Máximo de ${event.max_people} pessoa(s) na imagem`}</span></div>${reason ? `<p class="footnote">${reason}</p>` : ''}${event.clips.map((clip,i) => `<article class="clip-card">${clip.state === 'ready' ? `<video class="event-video" controls preload="metadata" playsinline poster="/media/${clip.id}.jpg" src="/media/${clip.id}${clip.analyzed && event.analysis_state==='complete'?'.analyzed':''}.mp4"></video>` : `<p class="muted small">${escapeHTML(deliveryLabel(clip,event))}</p>`}<div class="clip-meta"><span>Parte ${i+1} · ${duration(clip.duration)}</span><span>${escapeHTML(deliveryLabel(clip,event))}</span></div>${clip.error ? `<p class="clip-error">${escapeHTML(clip.error)}</p>` : ''}${clip.state === 'ready' && ['failed','uncertain','retry'].includes(clip.delivery) ? `<button class="button secondary compact" data-retry="${clip.id}">Tentar envio novamente</button>` : ''}</article>`).join('')}<div class="label-actions"><h3>Seu pai aparece neste registro?</h3><p>${event.ended ? 'Confirme após revisar as partes. A confirmação vale para todos os vídeos deste registro.' : 'Aguarde o fim da gravação para confirmar a identidade.'}</p><div class="label-buttons">${[['father','Sim, é meu pai'],['other','Outra pessoa'],['unknown','Não sei identificar']].map(([value,label]) => `<button class="button ${value==='father'?'primary':'secondary'} ${event.identity===value?'selected':''}" data-label="${value}" ${event.ended?'':'disabled'}>${label}</button>`).join('')}</div><p>${settings.father_only && settings.whatsapp_enabled ? 'Ao confirmar “Meu pai”, os vídeos disponíveis entram na fila de envio ao WhatsApp.' : 'Você pode configurar quais registros serão enviados na tela de configurações.'}</p></div>`;
  if(event.kind==='manual') {
    const running=event.analysis_state==='running';
    const complete=event.analysis_state==='complete';
    const ready=event.ended && event.clips.length && event.clips.every(clip=>clip.state==='ready');
    $('#event-content').insertAdjacentHTML('afterbegin',`<div class="manual-analysis"><strong>${complete?'Vídeo analisado':running?`Analisando: ${Math.round(event.analysis_progress)}%`:'Identificação posterior'}</strong><p>${running?'Pode continuar vendo a câmera. Esta tarefa usa processamento; cancele para liberar os recursos.':complete?'As pessoas detectadas estão abaixo. Revise as sugestões e confirme quem apareceu.':'Analise a gravação para detectar pessoas e comparar rostos. O vídeo original é preservado.'}</p>${event.analysis_error?`<p class="clip-error">${escapeHTML(event.analysis_error)}</p>`:''}${running?'<button class="button secondary compact" data-cancel-analysis>Cancelar análise</button>':!complete?`<button class="button primary compact" data-analyze-event="${event.id}" ${ready?'':'disabled'}>Analisar vídeo</button><small>${ready?'Usa processamento da máquina.':'Aguarde o fim da gravação e a preparação do vídeo.'}</small>`:''}<button class="text-button" data-refresh-event="${event.id}">Atualizar registro ↻</button></div>`);
    if(running) $$('#event-content [data-label]').forEach(button=>button.disabled=true);
  }
  if (event.people?.length) $('#event-content .label-actions').innerHTML = personTracksHTML(event);
  else $('#event-content .label-actions').insertAdjacentHTML('beforeend','<p class="small muted">Este registro não tem imagens individuais para ensinar. Novos registros com a comparação ativa terão uma identificação por pessoa.</p>');
  if (!$('#event-dialog').open) $('#event-dialog').showModal();
}
document.addEventListener('click', event => {
  const eventButton = event.target.closest('[data-event]');
  if (eventButton) {
    action(eventButton, async () => {openEvent(await api(`/api/events/${eventButton.dataset.event}`));});
  }
  const labelButton = event.target.closest('[data-label]');
  if (labelButton) action(labelButton, async () => {
    await api(`/api/events/${selectedEvent.id}`, {method:'PATCH', body:JSON.stringify({identity:labelButton.dataset.label,note:selectedEvent.note})});
    selectedEvent.identity = labelButton.dataset.label;
    openEvent(selectedEvent); toast('Identificação salva.'); await refresh();
  });
  const retryButton = event.target.closest('[data-retry]');
  if (retryButton && confirm('Confira se este vídeo já chegou ao WhatsApp. Tentar novamente pode repetir um envio cuja confirmação se perdeu. Continuar?')) action(retryButton, async () => {
    await api(`/api/clips/${retryButton.dataset.retry}/retry`, {method:'POST'});
    selectedEvent.clips.find(c => c.id === retryButton.dataset.retry).delivery = 'pending';
    openEvent(selectedEvent); toast('Vídeo devolvido à fila.');
  });
  const confirmTrack = event.target.closest('[data-confirm-track]');
  if (confirmTrack) action(confirmTrack, async () => {
    const track = confirmTrack.dataset.confirmTrack;
    const person = $(`[data-track-person="${track}"]`).value;
    if (!person) throw new Error('Escolha o nome da pessoa antes de confirmar.');
    const sample = $(`input[name="sample-${track}"]:checked`)?.value || null;
    await api(`/api/person-tracks/${track}`,{method:'PATCH',body:JSON.stringify({person_id:person,sample_id:sample})});
    await refresh();openEvent(await api(`/api/events/${selectedEvent.id}`));
    toast(sample?'Identificação salva. Imagem adicionada ao aprendizado.':'Presença confirmada; não havia imagem adequada para aprender.');
  });
  const clearTrack = event.target.closest('[data-clear-track]');
  if (clearTrack) action(clearTrack, async () => {
    await api(`/api/person-tracks/${clearTrack.dataset.clearTrack}`,{method:'PATCH',body:JSON.stringify({person_id:null})});
    await refresh();openEvent(await api(`/api/events/${selectedEvent.id}`));toast('Identificação e exemplos desta pessoa no registro removidos.');
  });
  const refreshEvent = event.target.closest('[data-refresh-event]');
  if (refreshEvent) action(refreshEvent, async () => openEvent(await api(`/api/events/${refreshEvent.dataset.refreshEvent}`)));
  const newPerson = event.target.closest('[data-new-person]');
  if (newPerson) action(newPerson, async () => {
    const name = prompt('Nome da pessoa:');if(!name?.trim()) return;
    await api('/api/people',{method:'POST',body:JSON.stringify({name:name.trim()})});
    await refresh();openEvent(await api(`/api/events/${selectedEvent.id}`));toast('Pessoa cadastrada. Agora selecione o nome nas imagens.');
  });
  const rename = event.target.closest('[data-rename-person]');
  if (rename) action(rename, async () => {
    const name=prompt('Nome da pessoa:',profiles.find(p=>p.id===rename.dataset.renamePerson)?.name);if(!name?.trim())return;
    await api(`/api/people/${rename.dataset.renamePerson}`,{method:'PATCH',body:JSON.stringify({name:name.trim()})});await refresh();
  });
  const forget = event.target.closest('[data-forget-person]');
  if (forget && confirm('Esquecer os exemplos desta pessoa? As confirmações no histórico serão mantidas, mas novas sugestões precisarão de novos exemplos.')) action(forget, async () => {
    await api(`/api/people/${forget.dataset.forgetPerson}/forget`,{method:'POST'});await refresh();toast('Exemplos removidos do aprendizado.');
  });
  const remove = event.target.closest('[data-delete-person]');
  if (remove && confirm('Excluir este perfil e remover suas identificações e exemplos? Os vídeos serão preservados.')) action(remove, async () => {
    await api(`/api/people/${remove.dataset.deletePerson}`,{method:'DELETE'});await refresh();toast('Perfil excluído.');
  });
});
$('#person-form').addEventListener('submit', event => {
  event.preventDefault();
  action($('#person-form button'),async()=>{
    await api('/api/people',{method:'POST',body:JSON.stringify({name:$('#person-name').value.trim()})});
    $('#person-name').value='';await refresh();toast('Pessoa cadastrada. Identifique as imagens dela no histórico.');
  });
});
$$('.close-dialog').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
$('#event-dialog').addEventListener('close', () => $$('#event-dialog video').forEach(video => {video.pause();video.removeAttribute('src');video.load();}));
$$('[data-filter]').forEach(button => button.addEventListener('click', () => {
  historyFilter = button.dataset.filter; offset = 0;
  $$('[data-filter]').forEach(b => b.classList.toggle('active', b===button));
  loadHistory().catch(error => toast(error.message,true));
}));
$('#previous-page').addEventListener('click', () => {offset=Math.max(0,offset-20);loadHistory().catch(e=>toast(e.message,true));});
$('#next-page').addEventListener('click', () => {offset+=20;loadHistory().catch(e=>toast(e.message,true));});
$('#settings-form').addEventListener('submit', event => {
  event.preventDefault();
  action($('#save-settings'), async () => {
    const next = {...settings}, form = event.currentTarget || $('#settings-form');
    for (const [name, value] of Object.entries(next)) {
      const input = form.elements.namedItem(name); if (!input) continue;
      next[name] = input.type === 'checkbox' ? input.checked : typeof value === 'number' ? Number(input.value) : input.value;
    }
    settings = await api(cameraPath('/api/settings'),{method:'PUT',body:JSON.stringify(next)});
    fillSettings(); toast('Configurações salvas.'); await refresh();
  });
});
$('#toggle-analysis').addEventListener('click',event=>action(event.currentTarget,async()=>{
  await api(cameraPath(`/api/analysis/${settings.analysis_enabled?'pause':'resume'}`),{method:'POST'});
  await refresh();
}));
$('#toggle-recording').addEventListener('click',event=>action(event.currentTarget,async()=>{
  const recording=status.camera.manual_requested || status.camera.manual_recording;
  await api(cameraPath(`/api/recording/${recording?'stop':'start'}`),{method:'POST'});
  await refresh();toast(recording?'Gravação encerrando. O vídeo ficará no histórico.':'Gravação manual solicitada.');
}));
$('#fullscreen-camera').addEventListener('click',()=>{
  $('.live-panel').requestFullscreen().catch(()=>toast('Tela cheia indisponível neste navegador.',true));
});
$('#cancel-offline').addEventListener('click',event=>action(event.currentTarget,async()=>{
  await api('/api/offline/cancel',{method:'POST'});await refresh();
}));
document.addEventListener('click',event=>{
  const analyze=event.target.closest('[data-analyze-event]');
  if(analyze) action(analyze,async()=>{
    await api(`/api/events/${analyze.dataset.analyzeEvent}/analyze`,{method:'POST'});
    openEvent(await api(`/api/events/${analyze.dataset.analyzeEvent}`));await refresh();
  });
  const cancel=event.target.closest('[data-cancel-analysis]');
  if(cancel) action(cancel,async()=>{
    await api('/api/offline/cancel',{method:'POST'});
    openEvent(await api(`/api/events/${selectedEvent.id}`));await refresh();
  });
});
$('#toggle-monitor').addEventListener('click', event => action(event.currentTarget, async () => {
  const result = await api(cameraPath(`/api/monitor/${settings.enabled?'stop':'start'}`), {method:'POST'});
  settings.enabled = result.enabled; renderStatus(); await refresh();
}));
$('#connect-whatsapp').addEventListener('click', event => action(event.currentTarget, async () => {
  if (status?.whatsapp.state === 'connected') {location.hash='settings';return;}
  $('#whatsapp-dialog').showModal();
  $('#qr-message').textContent='Preparando conexão…'; $('#qr-image').classList.add('hidden');
  try {await api('/api/whatsapp/connect',{method:'POST'});await refresh();}
  catch (error) {$('#qr-message').textContent=error.message;throw error;}
}));
async function refresh() {
  if (polling) return;
  polling = true;
  const requestedCamera=selectedCamera;
  try {
    const [nextStatus, recent, nextSettings] = await Promise.all([api(cameraPath('/api/status')),api('/api/events?limit=3'),api(cameraPath('/api/settings'))]);
    if (requestedCamera!==selectedCamera) return;
    status = nextStatus; settings = nextSettings; recentEvents = recent.events;
    profiles = status.recognition?.profiles || [];
    $('#connection-alert').classList.add('hidden');
    renderCameraList(); renderStatus(); renderRecent();
    if ($('#event-dialog').open && selectedEvent?.analysis_state==='running') {
      const updated=await api(`/api/events/${selectedEvent.id}`);
      if ($('#event-dialog').open && selectedEvent.id===updated.id) {
        if(updated.analysis_state==='running') {
          selectedEvent=updated;
          $('#event-content .manual-analysis strong').textContent=`Analisando: ${Math.round(updated.analysis_progress)}%`;
        } else openEvent(updated);
      }
    }
    if (activePage === 'history') await loadHistory();
    if (activePage === 'people') renderProfiles();
  } catch (error) {
    if(error.status===404) {
      try {
        const available=await api('/api/cameras');
        if(!available.cameras.some(c=>c.id===selectedCamera)) {
          selectedCamera='main';$('#live-image').removeAttribute('src');streamActive=false;
          settings=await api('/api/settings');fillSettings();
          setTimeout(refresh,0);return;
        }
      } catch {}
    }
    $('#connection-alert').classList.remove('hidden');
    $('#live-image').classList.add('hidden'); $('#camera-placeholder').classList.remove('hidden');
    $('#camera-placeholder-title').textContent='Sem conexão com o servidor';
    $('#camera-placeholder-description').textContent='Aguardando restabelecer a conexão.';
    $('#recording-badge').classList.add('hidden');
    if (status) status.camera.state = 'offline';
  } finally {polling=false;}
}
function updateStream() {
  const wanted = activePage === 'overview' && !document.hidden && status?.camera.state === 'online';
  if (wanted && !streamActive) {
    $('#live-image').src = cameraPath('/api/stream.mjpeg?t=' + Date.now());
    streamActive = true;
    $('#live-image').classList.remove('hidden');
    $('#camera-placeholder').classList.add('hidden');
  } else if (!wanted && streamActive) {
    $('#live-image').removeAttribute('src');
    streamActive = false;
  }
}
$('#live-image').addEventListener('error', () => {
  $('#live-image').removeAttribute('src');streamActive=false;
  setTimeout(updateStream,1500);
});
document.addEventListener('visibilitychange',()=>{updateStream();if(status)renderCameraList();});
document.addEventListener('click', event => {
  const button=event.target.closest('[data-remove-face]');
  if (button) action(button,async()=>{
    await api(`/api/people/${button.dataset.person}/faces/${button.dataset.removeFace}`,{method:'DELETE'});
    await refresh();toast('Foto removida do reconhecimento.');
  });
});
function renderCameraList() {
  knownCameras=status.cameras || [];
  const select=$('#camera-select');
  const options=knownCameras.map(c=>`<option value="${c.id}">${escapeHTML(c.name)}</option>`).join('');
  if(select.innerHTML!==options) {select.innerHTML=options;select.value=selectedCamera;}
  $('#remove-camera').disabled=selectedCamera==='main';
  const grid=$('#camera-grid');
  grid.hidden=knownCameras.length<2;
  for(const tile of [...grid.children]) if(!knownCameras.some(c=>c.id===tile.dataset.camera)) tile.remove();
  for(const camera of knownCameras) {
    let tile=grid.querySelector(`[data-camera="${camera.id}"]`);
    if(!tile) {
      tile=document.createElement('button');tile.type='button';tile.className='camera-tile';tile.dataset.camera=camera.id;
      tile.innerHTML='<img alt=""><strong></strong><span></span>';
      tile.addEventListener('click',()=>switchCamera(camera.id));grid.append(tile);
    }
    tile.classList.toggle('selected',camera.id===selectedCamera);
    tile.setAttribute('aria-pressed',String(camera.id===selectedCamera));
    tile.querySelector('strong').textContent=camera.name;
    tile.querySelector('span').textContent=({online:camera.analysis_active?'Ao vivo · análise ativa':'Ao vivo · análise pausada',paused:'Pausada',offline:'Sem sinal',connecting:'Conectando'})[camera.state]+(camera.manual_recording?' · gravando':'');
    const img=tile.querySelector('img');
    if(activePage==='overview' && !document.hidden && camera.state==='online') {
      img.src=`/api/snapshot?camera_id=${camera.id}&t=${Date.now()}`;img.hidden=false;img.alt=`Prévia de ${camera.name}`;
    } else {img.removeAttribute('src');img.hidden=true;}
  }
}
async function switchCamera(id) {
  if(id===selectedCamera)return;
  selectedCamera=id;
  $('#camera-select').value=id;
  $('#live-image').removeAttribute('src');streamActive=false;
  $('#camera-select').disabled=true;
  try {
    while(polling) await new Promise(resolve=>setTimeout(resolve,50));
    await refresh();fillSettings();
  } finally {$('#camera-select').disabled=false;}
}
async function loadHistoryCameras() {
  const historical=await api('/api/event-cameras');
  const names=new Map(historical.map(c=>[c.id,c.name || 'Câmera principal']));
  for(const camera of knownCameras) names.set(camera.id,camera.name);
  $('#history-camera').innerHTML='<option value="">Todas as câmeras</option>'+[...names].map(([id,name])=>`<option value="${escapeHTML(id)}">${escapeHTML(name)}</option>`).join('');
  $('#history-camera').value=historyCamera;
}
$('#camera-select').addEventListener('change',e=>switchCamera(e.target.value));
$('#history-camera').addEventListener('change',e=>{historyCamera=e.target.value;offset=0;loadHistory().catch(e=>toast(e.message,true));});
$('#add-camera').addEventListener('click',()=>$('#camera-dialog').showModal());
$('#camera-form').addEventListener('submit',e=>{
  e.preventDefault();const form=e.currentTarget;
  action(form.querySelector('button'),async()=>{
    const created=await api('/api/cameras',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(form)))});
    $('#camera-dialog').close();form.reset();
    await switchCamera(created.id);location.hash='settings';toast('Câmera cadastrada. Revise as configurações e inicie a captura.');
  });
});
$('#remove-camera').addEventListener('click',e=>{
  if(!confirm('Remover esta câmera e encerrar suas gravações em andamento? Os vídeos, o histórico e os rostos cadastrados serão preservados.'))return;
  action(e.currentTarget,async()=>{
    await api(`/api/cameras/${selectedCamera}`,{method:'DELETE',signal:AbortSignal.timeout(35000)});
    await switchCamera('main');toast('Câmera removida. Histórico preservado.');
  });
});
for(const [id,operation] of [['pause-all-analysis','pause'],['resume-all-analysis','resume']]) {
  $('#'+id).addEventListener('click',e=>action(e.currentTarget,async()=>{
    await api(`/api/analysis-all/${operation}`,{method:'POST'});await refresh();
    toast(operation==='pause'?'Análises pausadas em todas as câmeras. Os vídeos continuam.':'Análises retomadas em todas as câmeras.');
  }));
}
async function init() {
  $('#today-date').textContent = new Date().toLocaleDateString('pt-BR',{day:'numeric',month:'long',year:'numeric',timeZone:'America/Sao_Paulo'});
  try { settings=await api('/api/settings');fillSettings();route();await refresh(); }
  catch(error) {toast(error.message,true);$('#connection-alert').classList.remove('hidden');}
  setInterval(refresh,3000);
  setInterval(()=>{$('#camera-clock').textContent=new Date().toLocaleTimeString('pt-BR',{timeZone:'America/Sao_Paulo'});},1000);
}
init();
