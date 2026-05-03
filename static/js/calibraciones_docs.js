(function(){
  const $ = (q)=>document.querySelector(q);
  const stationSel = $("#calStation");
  const tabTanks = $("#tabTanks");
  const tabProbe = $("#tabProbe");
  const panelTanks = $("#panelTanks");
  const panelProbe = $("#panelProbe");
  const tankList = $("#tankList");
  const btnAddTank = $("#btnAddTank");
  const probeCards = $("#probeCards");

  // PDF preview modal
  const pdfModal = $("#pdfModal");
  const pdfModalTitle = $("#pdfModalTitle");
  const pdfModalFrame = $("#pdfModalFrame");
  const pdfModalOpen = $("#pdfModalOpen");
  const pdfModalClose = $("#pdfModalClose");
  const pdfModalPrint = $("#pdfModalPrint");

  function esc(s){
    return String(s||'').replace(/[&<>"']/g, m=>({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[m]));
  }

  // ---- CSRF helpers (project uses X-CSRF-Token) ----
  function csrfToken(){
    try{
      const meta = document.querySelector('meta[name="csrf-token"]');
      return meta ? (meta.getAttribute('content') || '') : '';
    }catch(e){
      return '';
    }
  }
  function withCsrf(headers={}){
    const t = csrfToken();
    return t ? ({...headers, 'X-CSRF-Token': t}) : headers;
  }

  function setActiveTab(which){
    const tanks = which === 'tanks';
    tabTanks.classList.toggle('active', tanks);
    tabProbe.classList.toggle('active', !tanks);
    panelTanks.classList.toggle('hidden', !tanks);
    panelProbe.classList.toggle('hidden', tanks);
  }

  tabTanks.addEventListener('click', ()=>setActiveTab('tanks'));
  tabProbe.addEventListener('click', ()=>setActiveTab('probe'));

  async function loadStations(){
    stationSel.innerHTML = `<option value="">Cargando…</option>`;
    const r = await fetch('/api/stations');
    const j = await r.json().catch(()=>({stations:[]}));
    const stations = j.stations || [];
    if(!stations.length){
      stationSel.innerHTML = `<option value="">Sin estaciones</option>`;
      return;
    }
    stationSel.innerHTML = `<option value="">Selecciona una estación…</option>` + stations.map(s=>{
      const code = s.code || ('ID '+s.id);
      const name = s.name || '';
      return `<option value="${s.id}">${esc(code)} — ${esc(name)}</option>`;
    }).join('');
  }

  async function listDocs(section, stationId){
    const url = `/api/docs?module=calibraciones&section=${encodeURIComponent(section)}&station_id=${encodeURIComponent(stationId||'')}`;
    const r = await fetch(url);
    if(!r.ok) return [];
    const j = await r.json().catch(()=>({ok:false}));
    if(!j.ok) return [];
    return j.items || [];
  }

  // ---- Tanques (Calibraciones) ----
  async function listTanks(stationId){
    const r = await fetch(`/api/calibraciones/tanks?station_id=${encodeURIComponent(stationId||'')}`);
    if(!r.ok) return [];
    const j = await r.json().catch(()=>({ok:false}));
    if(!j.ok) return [];
    return j.items || [];
  }

  async function createTank(stationId, name){
    const r = await fetch('/api/calibraciones/tanks', {
      method: 'POST',
      headers: withCsrf({'Content-Type':'application/json'}),
      body: JSON.stringify({station_id: stationId, name})
    });
    const j = await r.json().catch(()=>({ok:false}));
    if(!r.ok || !j.ok){
      alert(j.message || j.error || 'No se pudo crear el tanque');
      return null;
    }
    return j.id;
  }

  async function uploadTankPdf(tankId, file, kind='calibracion'){
    const fd = new FormData();
    fd.append('file', file);
    const q = kind ? (`?kind=${encodeURIComponent(kind)}`) : '';
    const r = await fetch(`/api/calibraciones/tanks/${tankId}/upload${q}`, {method:'POST', body: fd, headers: withCsrf({})});
    const j = await r.json().catch(()=>({ok:false}));
    if(!r.ok || !j.ok){
      alert(j.message || j.error || 'No se pudo subir el PDF');
      return false;
    }
    return true;
  }

  function fileUrl(relpath, inline=false){
    if(!relpath) return '';
    const base = '/uploads/' + String(relpath).replace(/\\/g,'/');
    return inline ? (base + (base.includes('?') ? '&' : '?') + 'inline=1') : base;
  }

  function openInNewTab(url){
    if(!url) return false;
    try{
      // More reliable than window.open in some popup-blocking scenarios
      const a = document.createElement('a');
      a.href = url;
      a.target = '_blank';
      a.rel = 'noopener';
      document.body.appendChild(a);
      a.click();
      a.remove();
      return true;
    }catch(e){
      try{ window.open(url, '_blank'); return true; }catch(_){ return false; }
    }
  }

  function showPdfModal(title, urlInline){
    if(!urlInline){
      alert('No hay PDF para visualizar');
      return false;
    }
    if(!pdfModal || !pdfModalFrame){
      return openInNewTab(urlInline);
    }
    if(pdfModalTitle) pdfModalTitle.textContent = title || 'Vista previa';
    if(pdfModalOpen) pdfModalOpen.setAttribute('href', urlInline);
    pdfModalFrame.src = urlInline;
    pdfModal.classList.remove('hidden');
    pdfModal.setAttribute('aria-hidden','false');
    return true;
  }

  function hidePdfModal(){
    if(!pdfModal) return;
    pdfModal.classList.add('hidden');
    pdfModal.setAttribute('aria-hidden','true');
    if(pdfModalFrame) pdfModalFrame.src = 'about:blank';
  }

  function printFromModal(){
    if(!pdfModalFrame) return;
    try{
      const w = pdfModalFrame.contentWindow;
      if(w) w.print();
    }catch(e){
      // best-effort
    }
  }

  if(pdfModal){
    pdfModal.addEventListener('click', (ev)=>{
      const t = ev.target;
      if(t && t.getAttribute && t.getAttribute('data-act') === 'close') hidePdfModal();
    });
  }
  if(pdfModalClose) pdfModalClose.addEventListener('click', hidePdfModal);
  if(pdfModalPrint) pdfModalPrint.addEventListener('click', printFromModal);

  function forceDownload(url){
    if(!url) return;
    // Trigger download without leaving the page
    try{
      const a = document.createElement('a');
      a.href = url;
      a.rel = 'noopener';
      a.download = '';
      document.body.appendChild(a);
      a.click();
      a.remove();
    }catch(e){
      window.location.href = url;
    }
  }

  function openForPrint(url){
    if(!url){ alert('No hay PDF para imprimir'); return; }
    const ok = openInNewTab(url);
    if(!ok){
      alert('Tu navegador bloqueó la ventana. Permite popups o usa el botón Ver y luego imprime.');
      return;
    }
    // Best-effort: many browsers disallow cross-window print() on PDF viewers.
  }

  async function uploadPdf({stationId, section, title, file}){
    const fd = new FormData();
    fd.append('module', 'calibraciones');
    fd.append('section', section);
    fd.append('title', title);
    fd.append('station_id', stationId);
    fd.append('file', file);

    const r = await fetch('/api/docs/upload', {method:'POST', body: fd, headers: withCsrf({})});
    const j = await r.json().catch(()=>({ok:false}));
    if(!r.ok || !j.ok){
      alert(j.message || j.error || 'No se pudo subir el PDF');
      return false;
    }
    return true;
  }

  function makeFilePicker(onPick){
    const inp = document.createElement('input');
    inp.type = 'file';
    inp.accept = '.pdf';
    inp.style.display = 'none';
    inp.addEventListener('change', ()=>{
      const f = inp.files && inp.files[0];
      if(f) onPick(f);
      inp.remove();
    });
    document.body.appendChild(inp);
    inp.click();
  }

  async function renderTanks(){
    const stationId = stationSel.value;
    if(!stationId){
      tankList.innerHTML = `<div class="muted">Selecciona una estación…</div>`;
      return;
    }
    tankList.innerHTML = `<div class="muted">Cargando tanques…</div>`;
    const items = await listTanks(stationId);
    if(!items.length){
      // Empty state con el mismo estilo de tarjetas/botones que Sonda/Temperatura
      tankList.innerHTML = `
        <div class="probe-card tank-card span-2" style="align-self:start">
          <h3>Sin tanques registrados</h3>
          <div class="meta">Crea un tanque para esta estación y sube su PDF de calibración.</div>
          <div class="row">
            <button type="button" class="btn small" disabled>🖨️ Imprimir</button>
            <button type="button" class="btn small" data-act="add">➕ Agregar tanque</button>
            <button type="button" class="btn small" disabled>👁️ Ver</button>
            <button type="button" class="btn small" disabled>⬇️ Descargar</button>
          </div>
        </div>
      `;

      const addBtn = tankList.querySelector('[data-act="add"]');
      if(addBtn){
        addBtn.addEventListener('click', ()=>startAddTank());
      }
      return;
    }

    // Misma UI que Sonda/Temperatura: tarjetas con fila de botones
    tankList.innerHTML = items
      .sort((a,b)=>String(a.name||'').localeCompare(String(b.name||'')))
      .map(it=>{
        const title = it.name || 'Tanque';
        const urlInline = it.pdf_path ? fileUrl(it.pdf_path, true) : '';
        const urlDl = it.pdf_path ? fileUrl(it.pdf_path, false) : '';
        const when = it.pdf_uploaded_at ? String(it.pdf_uploaded_at).slice(0,19).replace('T',' ') : '';
        const meta = it.pdf_path
          ? `✅ PDF cargado — Última subida: ${esc(when)}`
          : '⏳ Sin PDF cargado';

        return `
          <div class="probe-card tank-card" data-tank-id="${it.id}" data-title="${esc(title)}">
            <h3>${esc(title)}</h3>
            <div class="meta">${meta}</div>
            <div class="row">
              <button type="button" class="btn small" data-act="print" ${urlInline?`data-url="${esc(urlInline)}"`:''}>🖨️ Imprimir</button>
              <button type="button" class="btn small" data-act="upload">⬆️ Subir PDF</button>
              <button type="button" class="btn small" data-act="view" ${urlInline?`data-url="${esc(urlInline)}"`: 'disabled'}>👁️ Ver</button>
              <button type="button" class="btn small" data-act="download" ${urlDl?`data-url="${esc(urlDl)}"`: 'disabled'}>⬇️ Descargar</button>
            </div>
          </div>
        `;
      }).join('');

    // bind actions
    tankList.querySelectorAll('.tank-card').forEach(row=>{
      const title = row.getAttribute('data-title') || 'Tanque';
      const tankId = row.getAttribute('data-tank-id');
      row.querySelectorAll('[data-act]').forEach(btn=>{
        const act = btn.getAttribute('data-act');
        if(act === 'view'){
          btn.addEventListener('click', ()=>{
            const url = btn.getAttribute('data-url');
            if(url) showPdfModal(title, url);
          });
        }
        if(act === 'print'){
          btn.addEventListener('click', ()=>{
            const url = btn.getAttribute('data-url');
            if(!url){ alert('No hay PDF para imprimir'); return; }
            showPdfModal(title, url);
            if(pdfModalFrame){
              const once = ()=>{ pdfModalFrame.removeEventListener('load', once); setTimeout(printFromModal, 50); };
              pdfModalFrame.addEventListener('load', once);
            }
          });
        }
        if(act === 'download'){
          btn.addEventListener('click', ()=>{
            const url = btn.getAttribute('data-url');
            if(url) forceDownload(url);
          });
        }
        if(act === 'upload'){
          btn.addEventListener('click', ()=>{
            makeFilePicker(async (file)=>{
              if(!tankId){
                alert('Tank ID no encontrado');
                return;
              }
              const ok = await uploadTankPdf(tankId, file, 'calibracion');
              if(ok){
                await renderTanks();
                await renderProbeTemp();
              }
            });
          });
        }
      });
    });
  }

  async function renderProbeTemp(){
    const stationId = stationSel.value;
    if(!stationId){
      probeCards.innerHTML = `<div class="muted" style="padding:14px">Selecciona una estación…</div>`;
      return;
    }

    probeCards.innerHTML = `<div class="muted" style="padding:14px">Cargando…</div>`;
    const tanks = await listTanks(stationId);

    if(!tanks.length){
      probeCards.innerHTML = `
        <div class="probe-card span-2">
          <h3>Sin tanques registrados</h3>
          <div class="meta">Primero crea tanques en la pestaña “Calibración de Tanques”. Cada tanque tendrá documentos de <b>Sonda</b> y <b>Temperatura</b>.</div>
        </div>
      `;
      return;
    }

    function mkCard(kindTitle, kindKey, tank){
      const title = `${kindTitle} — ${tank.name || 'Tanque'}`;
      const path = kindKey === 'sonda' ? tank.sonda_pdf_path : tank.temp_pdf_path;
      const when = kindKey === 'sonda' ? tank.sonda_pdf_uploaded_at : tank.temp_pdf_uploaded_at;
      const urlInline = path ? fileUrl(path, true) : '';
      const urlDl = path ? fileUrl(path, false) : '';
      const meta = when ? `Última subida: ${esc(String(when).slice(0,19).replace('T',' '))}` : 'Sin PDF cargado';
      return `
        <div class="probe-card" data-tank-id="${tank.id}" data-kind="${esc(kindKey)}" data-title="${esc(title)}">
          <h3>${esc(kindTitle)}</h3>
          <div class="meta">${esc(tank.name || 'Tanque')}</div>
          <div class="meta">${meta}</div>
          <div class="row">
            <button type="button" class="btn small" data-act="print" ${urlInline?`data-url="${esc(urlInline)}"`:''}>🖨️ Imprimir</button>
            <button type="button" class="btn small" data-act="upload">⬆️ Subir PDF</button>
            <button type="button" class="btn small" data-act="view" ${urlInline?`data-url="${esc(urlInline)}"`: 'disabled'}>👁️ Ver</button>
            <button type="button" class="btn small" data-act="download" ${urlDl?`data-url="${esc(urlDl)}"`: 'disabled'}>⬇️ Descargar</button>
          </div>
        </div>
      `;
    }

    const parts = [];
    tanks
      .sort((a,b)=>String(a.name||'').localeCompare(String(b.name||'')))
      .forEach(t=>{
        parts.push(`
          <div class="tank-group">
            <div class="tg-title">${esc(t.name || 'Tanque')}</div>
            <div class="tg-sub">Documentos de sonda y temperatura para este tanque.</div>
          </div>
        `);
        parts.push(mkCard('Sonda', 'sonda', t));
        parts.push(mkCard('Temperatura', 'temperatura', t));
      });

    probeCards.innerHTML = parts.join('');

    probeCards.querySelectorAll('.probe-card').forEach(c=>{
      const tankId = c.getAttribute('data-tank-id');
      const kind = c.getAttribute('data-kind');
      const title = c.getAttribute('data-title') || '';
      c.querySelectorAll('[data-act]').forEach(btn=>{
        const act = btn.getAttribute('data-act');
        if(act === 'view'){
          btn.addEventListener('click', ()=>{
            const url = btn.getAttribute('data-url');
            if(url) showPdfModal(title, url);
          });
        }
        if(act === 'print'){
          btn.addEventListener('click', ()=>{
            const url = btn.getAttribute('data-url');
            if(!url){ alert('No hay PDF para imprimir'); return; }
            showPdfModal(title, url);
            if(pdfModalFrame){
              const once = ()=>{ pdfModalFrame.removeEventListener('load', once); setTimeout(printFromModal, 50); };
              pdfModalFrame.addEventListener('load', once);
            }
          });
        }
        if(act === 'download'){
          btn.addEventListener('click', ()=>{
            const url = btn.getAttribute('data-url');
            if(url) forceDownload(url);
          });
        }
        if(act === 'upload'){
          btn.addEventListener('click', ()=>{
            makeFilePicker(async (file)=>{
              const ok = await uploadTankPdf(tankId, file, kind);
              if(ok) await renderProbeTemp();
            });
          });
        }
      });
    });
  }

  function startAddTank(){
    const stationId = stationSel.value;
    if(!stationId){ alert('Selecciona una estación'); return; }
    const label = (prompt('Nombre del tanque (ej. "Tanque 1", "Diésel", "Magna")') || '').trim();
    if(!label) return;
    (async ()=>{
      const tankId = await createTank(stationId, label);
      if(!tankId) return;
      await renderTanks();
      await renderProbeTemp();
      // Opción: subir PDF en el mismo paso
      const doUploadNow = confirm('¿Quieres subir el PDF de este tanque ahora?');
      if(!doUploadNow) return;
      makeFilePicker(async (file)=>{
        const ok = await uploadTankPdf(tankId, file, 'calibracion');
        if(ok){
          await renderTanks();
          await renderProbeTemp();
        }
      });
    })();
  }

  btnAddTank.addEventListener('click', ()=>startAddTank());

  stationSel.addEventListener('change', async ()=>{
    await renderTanks();
    await renderProbeTemp();
  });

  (async function init(){
    await loadStations();
    await renderTanks();
    await renderProbeTemp();
  })();
})();
