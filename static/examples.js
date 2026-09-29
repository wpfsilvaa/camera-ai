(() => {
  const dialog=$('#examples-dialog'), grid=$('#examples-grid');
  let personId, examples=[], limits={}, revision=0, busy=false;
  const origin=item=>item.source==='history'?`Histórico · registro #${item.event_id}`:'Foto cadastrada';
  const error=message=>{
    $('#examples-error').textContent=message;
    $('#examples-error').classList.toggle('hidden',!message);
  };
  function render() {
    const history=examples.filter(item=>item.source==='history').length;
    $('#examples-count').textContent=`${examples.length} exemplo(s) · Histórico: ${history}/${limits.history} · Fotos cadastradas: ${examples.length-history}/${limits.upload}`;
    const source=$('#examples-source').value;
    const visible=examples.filter(item=>source==='all'||item.source===source);
    visible.sort($('#examples-sort').value==='quality' ? (a,b)=>a.quality-b.quality || b.created-a.created : (a,b)=>b.created-a.created);
    grid.innerHTML=visible.map(item=>`<article class="example-card">
      <button type="button" class="example-thumbnail" data-view-example="${item.id}" data-source="${item.source}" aria-label="Ampliar exemplo de ${escapeHTML(origin(item))}"><img src="/people-media/${item.id}.jpg" alt="Rosto usado no reconhecimento" loading="lazy"></button>
      <strong>${escapeHTML(origin(item))}</strong><small>${date(item.created)}</small><small>Nitidez: ${Math.round(item.quality)}</small>
      <button type="button" class="button secondary compact" data-delete-example="${item.id}" data-source="${item.source}">Remover do aprendizado</button>
    </article>`).join('') || '<p class="muted">Nenhum exemplo para mostrar.</p>';
  }
  async function load() {
    const version=++revision;
    const result=await api(`/api/people/${personId}/examples`);
    if (version!==revision || !dialog.open) return;
    examples=result.examples;limits=result.limits;
    $('#examples-title').textContent=`Exemplos de ${result.person.name}`;
    render();
  }
  document.addEventListener('click',async event=>{
    const button=event.target.closest('[data-review-examples]');
    if (!button) return;
    personId=button.dataset.reviewExamples;
    examples=[];error('');$('#examples-source').value='all';$('#examples-sort').value='recent';
    $('#examples-title').textContent='Revisar exemplos';$('#examples-count').textContent='Carregando…';grid.replaceChildren();
    dialog.showModal();
    try {await load();} catch(failure){if(dialog.open)error(failure.message);}
  });
  for (const id of ['examples-source','examples-sort']) $('#'+id).addEventListener('change',()=>{if(!busy)render();});
  grid.addEventListener('click',async event=>{
    if (busy) return;
    const view=event.target.closest('[data-view-example]');
    if (view) {
      const item=examples.find(item=>item.id===view.dataset.viewExample && item.source===view.dataset.source);
      if (!item) return;
      $('#example-photo').src=`/people-media/${item.id}.jpg`;
      $('#example-photo-details').textContent=`${origin(item)} · ${date(item.created)} · Nitidez: ${Math.round(item.quality)}`;
      $('#example-photo-dialog').showModal();return;
    }
    const button=event.target.closest('[data-delete-example]');
    if (!button) return;
    busy=true;error('');button.disabled=true;button.textContent='Removendo…';
    $('#examples-close').disabled=true;
    $('#examples-source').disabled=true;$('#examples-sort').disabled=true;
    try {
      await api(`/api/people/${personId}/examples/${button.dataset.source}/${button.dataset.deleteExample}`,{method:'DELETE'});
      // Reflect the successful mutation even if a subsequent refresh fails.
      examples=examples.filter(item=>!(item.id===button.dataset.deleteExample && item.source===button.dataset.source));render();
      try {
        const recognition=await api('/api/people');
        if(status)status.recognition=recognition;
        renderProfiles();
      } catch { /* The regular status poll retries this refresh. */ }
    } catch(failure) {error(failure.message);button.disabled=false;button.textContent='Remover do aprendizado';}
    finally {
      busy=false;$('#examples-close').disabled=false;
      $('#examples-source').disabled=false;$('#examples-sort').disabled=false;
    }
  });
  $('#examples-close').addEventListener('click',()=>dialog.close());
  dialog.addEventListener('cancel',event=>{if(busy)event.preventDefault();});
  dialog.addEventListener('close',()=>{revision++;examples=[];grid.replaceChildren();});
  $('#example-photo-close').addEventListener('click',()=>$('#example-photo-dialog').close());
  $('#example-photo-dialog').addEventListener('close',()=>$('#example-photo').removeAttribute('src'));
})();
