// This dialog and file input stay mounted while the profile cards refresh.
(() => {
  const dialog = $('#face-dialog'), input = $('#face-file'), canvas = $('#face-canvas');
  const context = canvas.getContext('2d');
  let personId, photo, selection, anchor, busy = false, revision = 0;
  const error = message => {
    $('#face-error').textContent = message;
    $('#face-error').classList.toggle('hidden', !message);
  };
  function draw() {
    if (!photo) return;
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.drawImage(photo, 0, 0, canvas.width, canvas.height);
    const {x,y,w,h} = selection;
    context.fillStyle = '#0009';
    context.fillRect(0,0,canvas.width,y);
    context.fillRect(0,y,x,h);
    context.fillRect(x+w,y,canvas.width-x-w,h);
    context.fillRect(0,y+h,canvas.width,canvas.height-y-h);
    context.strokeStyle = '#b9f090'; context.lineWidth = 3;
    context.strokeRect(x+1,y+1,Math.max(0,w-2),Math.max(0,h-2));
  }
  function reset() {
    selection = {x:0,y:0,w:canvas.width,h:canvas.height};
    error('');draw();
  }
  function controls(disabled) {
    busy = disabled;
    for (const id of ['face-choose','face-reset','face-close','face-cancel']) $('#'+id).disabled = disabled;
    $('#face-save').disabled = disabled || !photo;
  }
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-face-upload]');
    if (!button) return;
    personId = button.dataset.faceUpload;
    $('#face-person').textContent = 'Pessoa: ' + (profiles.find(p=>p.id===personId)?.name || 'Perfil selecionado');
    error('');controls(false);dialog.showModal();
  });
  $('#face-choose').addEventListener('click', () => {input.value='';input.click();});
  input.addEventListener('change', async () => {
    const file = input.files?.[0];
    if (!file) return;
    const current = ++revision;
    photo = null;$('#face-editor').classList.add('hidden');controls(true);error('');
    $('#face-message').textContent = 'Abrindo foto…';
    let url;
    try {
      if (file.size > 8*1024*1024) throw new Error('A foto deve ter até 8 MB.');
      if (!['image/jpeg','image/png'].includes(file.type)) throw new Error('Escolha uma foto JPEG ou PNG.');
      url = URL.createObjectURL(file);
      const image = new Image();image.src=url;await image.decode();
      if (current !== revision || !dialog.open) return;
      if (image.naturalWidth*image.naturalHeight > 16_000_000) throw new Error('A foto deve ter até 16 megapixels.');
      photo=image;
      const scale=Math.min(1,900/image.naturalWidth,Math.max(160,innerHeight*.42)/image.naturalHeight);
      canvas.width=Math.round(image.naturalWidth*scale);canvas.height=Math.round(image.naturalHeight*scale);
      reset();$('#face-editor').classList.remove('hidden');
      $('#face-message').textContent = 'Foto carregada. Ajuste o recorte e clique em Salvar rosto.';
    } catch (failure) {
      error(failure.message || 'Não foi possível abrir esta foto.');
      $('#face-message').textContent = 'Escolha outra foto para continuar.';
    } finally {
      if (url) URL.revokeObjectURL(url);
      if (current === revision) controls(false);
    }
  });
  function point(event) {
    const bounds=canvas.getBoundingClientRect();
    return {x:Math.max(0,Math.min(canvas.width,(event.clientX-bounds.left)*canvas.width/bounds.width)),
            y:Math.max(0,Math.min(canvas.height,(event.clientY-bounds.top)*canvas.height/bounds.height))};
  }
  canvas.addEventListener('pointerdown', event => {
    if (!photo || busy || !event.isPrimary || event.button!==0) return;
    event.preventDefault();canvas.focus();anchor=point(event);canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener('pointermove', event => {
    if (!anchor || busy) return;
    const p=point(event);
    selection={x:Math.min(anchor.x,p.x),y:Math.min(anchor.y,p.y),w:Math.abs(p.x-anchor.x),h:Math.abs(p.y-anchor.y)};
    error('');draw();
  });
  for (const name of ['pointerup','pointercancel','lostpointercapture']) canvas.addEventListener(name,()=>{anchor=null;});
  canvas.addEventListener('keydown', event => {
    if (!photo || busy) return;
    const step=Math.max(1,canvas.width*.02), s=selection;
    if (event.key==='ArrowLeft') s.x=Math.max(0,s.x-step);
    else if (event.key==='ArrowRight') s.x=Math.min(canvas.width-s.w,s.x+step);
    else if (event.key==='ArrowUp') s.y=Math.max(0,s.y-step);
    else if (event.key==='ArrowDown') s.y=Math.min(canvas.height-s.h,s.y+step);
    else if (['+','=','-'].includes(event.key)) {
      const delta=event.key==='-'?-step:step;
      s.w=Math.max(10,Math.min(canvas.width-s.x,s.w+delta));
      s.h=Math.max(10,Math.min(canvas.height-s.y,s.h+delta));
    } else return;
    event.preventDefault();error('');draw();
  });
  $('#face-reset').addEventListener('click',reset);
  $('#face-save').addEventListener('click',async()=>{
    if (!photo || busy) return;
    controls(true);error('');$('#face-save').textContent='Salvando…';
    try {
      const sx=photo.naturalWidth/canvas.width,sy=photo.naturalHeight/canvas.height;
      const x=selection.x*sx,y=selection.y*sy,w=selection.w*sx,h=selection.h*sy;
      if (w<80 || h<80) throw new Error('O recorte está muito pequeno. Selecione o rosto inteiro, com uma margem.');
      const output=document.createElement('canvas'),scale=Math.min(1,1600/Math.max(w,h));
      output.width=Math.round(w*scale);output.height=Math.round(h*scale);
      output.getContext('2d').drawImage(photo,x,y,w,h,0,0,output.width,output.height);
      const blob=await new Promise(resolve=>output.toBlob(resolve,'image/jpeg',.94));
      if (!blob) throw new Error('Não foi possível preparar o recorte. Escolha a foto novamente.');
      await api(`/api/people/${personId}/faces`,{method:'POST',headers:{'Content-Type':'image/jpeg'},body:blob});
      // Fetch profiles directly so an overlapping status poll cannot hide the new photo.
      try {
        const recognition=await api('/api/people');
        if (status) status.recognition=recognition;
        renderProfiles();
      } catch { /* The periodic refresh will retry; the upload already succeeded. */ }
      dialog.close();toast('Rosto cadastrado com sucesso.');
    } catch (failure) {
      error(failure.message || 'Não foi possível cadastrar o rosto. Tente novamente.');
    } finally {controls(false);$('#face-save').textContent='Salvar rosto';}
  });
  for (const id of ['face-close','face-cancel']) $('#'+id).addEventListener('click',()=>dialog.close());
  dialog.addEventListener('cancel',event=>{if(busy)event.preventDefault();});
  dialog.addEventListener('close',()=>{
    revision++;photo=null;selection=null;anchor=null;input.value='';
    $('#face-editor').classList.add('hidden');$('#face-message').textContent='Nenhuma foto selecionada.';
    context.clearRect(0,0,canvas.width,canvas.height);controls(false);error('');
  });
})();
