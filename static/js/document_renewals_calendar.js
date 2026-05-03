(async()=>{
  const fromEl = qs('#dFrom'), toEl = qs('#dTo'), stationEl = qs('#fStation'), moduleEl = qs('#fModule'), urgEl = qs('#fUrgency'), qEl = qs('#fQ');
  const listEl = qs('#renewalList');
  const kTotal = qs('#kTotal'), kSoon = qs('#kSoon'), kCrit = qs('#kCrit'), kOver = qs('#kOver');
  const modal = qs('#detailModal'), mClose = qs('#mClose'), mTitle = qs('#mTitle'), mSub = qs('#mSub'), mBody = qs('#mBody'), mOpen = qs('#mOpen'), mFile = qs('#mFile'), mRenew = qs('#mRenew');
  let CURRENT = null;
  const MODULE_LABELS = {normativas:'Normativa', expediente_normativas:'Documento normativo'};
  const today = new Date();
  const first = new Date(today.getFullYear(), today.getMonth(), 1);
  const last = new Date(today.getFullYear(), today.getMonth()+2, 0);
  fromEl.value = first.toISOString().slice(0,10); toEl.value = last.toISOString().slice(0,10);

  const cal = new FullCalendar.Calendar(qs('#renewalCalendar'), {
    initialView:'dayGridMonth', locale:'es', height:720, events:[],
    eventDidMount(info){ const ext = info.event.extendedProps||{}; const tt = [ext.scope_label, ext.urgency_label, ext.folio].filter(Boolean).join(' · '); if(tt) info.el.title = tt; },
    eventClick(info){ info.jsEvent.preventDefault(); openDetail(info.event.extendedProps || {}); }
  });
  cal.render();

  function stationOptions(items, selected=''){ return ['<option value="">Todas</option>'].concat((items||[]).map(s=>`<option value="${s.id}" ${String(selected)===String(s.id)?'selected':''}>${_esc([s.code,s.name].filter(Boolean).join(' · '))}</option>`)).join(''); }
  function badge(text, klass=''){ return text ? `<span class="tag ${klass}">${_esc(text)}</span>` : ''; }
  function moduleLabel(v){ return MODULE_LABELS[v] || (v||'').replaceAll('_',' '); }
  function listRow(it){ return `<div class="eventrow" data-row-id="${it.id}"><div class="date">${_esc(it.date||'')}</div><div><div class="meta">${badge(moduleLabel(it.module),'info')}${badge(it.urgency_label||'', it.urgency==='vencido' ? 'bad' : (['hoy','critico'].includes(it.urgency)?'warn':'ok'))}${badge((it.status||'').replaceAll('_',' '))}</div><div style="font-weight:900;">${_esc(it.title||'')}</div><div class="help">${_esc(it.scope_label||'')}</div><div class="help">${_esc([it.folio,it.notes].filter(Boolean).join(' · '))}</div></div></div>`; }
  function openDetail(it){
    CURRENT = it;
    mTitle.textContent = it.title || 'Detalle';
    mSub.textContent = [it.scope_label, it.due_date, it.urgency_label].filter(Boolean).join(' · ');
    mBody.innerHTML = `
      <div class="grid cols-2">
        <div><div class="help">Módulo</div><div>${_esc(moduleLabel(it.module))}</div></div>
        <div><div class="help">Folio</div><div>${_esc(it.folio||'—')}</div></div>
        <div><div class="help">Estatus</div><div>${_esc((it.status||'').replaceAll('_',' '))}</div></div>
        <div><div class="help">Responsable</div><div>${_esc(it.responsible_name||'—')}</div></div>
        <div><div class="help">Días restantes</div><div>${it.days_left==null?'—':_esc(it.days_left)}</div></div>
        <div><div class="help">Notas</div><div>${_esc(it.notes||'—')}</div></div>
      </div>`;
    mOpen.href = it.url || '#';
    if(it.file_url){ mFile.hidden = false; mFile.href = it.file_url; } else { mFile.hidden = true; mFile.removeAttribute('href'); }
    modal.classList.add('show');
  }
  function closeModal(){ modal.classList.remove('show'); CURRENT = null; }
  mClose.onclick = closeModal; modal.addEventListener('click', e=>{ if(e.target===modal) closeModal(); });
  mRenew.onclick = async()=>{
    if(!CURRENT) return;
    const nd = prompt('Nueva fecha de vencimiento (YYYY-MM-DD):', CURRENT.due_date || '');
    if(!nd) return;
    try{ await api('/api/document-deadlines/'+CURRENT.id+'/renew', {method:'POST', body: JSON.stringify({new_due_date: nd})}); toast('Renovación guardada'); closeModal(); await load(); }catch(e){ toast('No se pudo renovar', e.message||''); }
  };

  async function load(){
    const qsx = new URLSearchParams({from:fromEl.value, to:toEl.value, station_id:stationEl.value||'', module:moduleEl.value||'', urgency:urgEl.value||'', q:qEl.value||''}).toString();
    const data = await api('/api/document-renewals-calendar?'+qsx);
    stationEl.innerHTML = stationOptions(data.stations||[], stationEl.value);
    const items = data.items || [];
    cal.removeAllEvents();
    items.forEach(it=> cal.addEvent({ title: it.title, start: it.date, allDay:true, color: it.color, extendedProps: it }));
    kTotal.textContent = data.summary.total || 0; kSoon.textContent = data.summary.proximos || 0; kCrit.textContent = data.summary.criticos || 0; kOver.textContent = data.summary.vencidos || 0;
    listEl.innerHTML = items.length ? items.map(listRow).join('') : '<div class="help">No hay renovaciones en el rango seleccionado.</div>';
    qsa('[data-row-id]').forEach(el=> el.onclick=()=>{ const id = Number(el.dataset.rowId); const item = items.find(x=>Number(x.id)===id); if(item) openDetail(item); });
  }

  qs('#btnReload').onclick = load;
  [fromEl,toEl,stationEl,moduleEl,urgEl].forEach(el=>el.addEventListener('change', load));
  qEl.addEventListener('keyup', ()=>{ clearTimeout(window.__renewQ); window.__renewQ = setTimeout(load, 250); });
  await load();
})();
