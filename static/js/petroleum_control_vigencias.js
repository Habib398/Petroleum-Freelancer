function csrfToken(){ const el=document.querySelector('meta[name="csrf-token"]'); return el ? el.getAttribute('content') : ''; }
async function api(url, options={}){
  const headers = options.headers || {};
  headers['X-CSRF-Token'] = csrfToken();
  if (!(options.body instanceof FormData) && !headers['Content-Type'] && options.body !== undefined){ headers['Content-Type'] = 'application/json'; }
  const res = await fetch(url, {...options, headers});
  const data = await res.json().catch(()=>null);
  if (!res.ok){ throw new Error((data && (data.message || data.error)) || 'Error'); }
  return data;
}
function toast(msg){ const el=document.getElementById('pcvToast'); if(!el) return; el.textContent=msg; el.hidden=false; clearTimeout(el._t); el._t=setTimeout(()=>el.hidden=true, 2800); }
const STATE = { meta:null, entries:[], byId:new Map() };
const $ = (id)=>document.getElementById(id);

function badgeStatus(kind, value, daysLeft){
  const map = {
    document_status: {
      vigente:['doc','Vigente'], debe_documento:['doc danger','Debe documento'], en_revision:['doc warn','En revisión'], vencido:['doc danger','Vencido'], no_aplica:['doc muted','No aplica']
    },
    payment_status: {
      pagado:['pay','Pagado'], pendiente:['pay warn','Pendiente'], vencido:['pay danger','Vencido'], no_aplica:['pay','No aplica']
    },
    renewal_state: {
      vigente:['renew', daysLeft==null ? 'Vigente' : `Vence en ${daysLeft} días`],
      proximo:['renew warn', daysLeft==null ? 'Por vencer' : `Renueva en ${daysLeft} días`],
      vencido:['renew danger', daysLeft==null ? 'Vencido' : `Vencido ${Math.abs(daysLeft)} días`],
      sin_fecha:['renew muted', 'Sin fecha']
    }
  };
  const conf = (map[kind] || {})[value] || ['doc muted', value || '—'];
  return `<span class="pcv-badge ${conf[0]}">${conf[1]}</span>`;
}
function optList(select, items, placeholder, labelFn){
  if(!select) return;
  select.innerHTML = '';
  const first = document.createElement('option');
  first.value = '';
  first.textContent = placeholder;
  select.appendChild(first);
  items.forEach(it=>{
    const op=document.createElement('option'); op.value=String(it.id); op.textContent = labelFn ? labelFn(it) : (it.title || it.name || it.code || it.id); select.appendChild(op);
  });
}
function renderSummary(summary){
  $('sumTotal').textContent = summary.total || 0;
  $('sumVigentes').textContent = summary.vigentes || 0;
  $('sumPorVencer').textContent = summary.por_vencer || 0;
  $('sumVencidos').textContent = summary.vencidos || 0;
  $('sumPagos').textContent = summary.pagos_pendientes || 0;
  $('sumDocs').textContent = summary.documentos_pendientes || 0;
}
function renderOwners(){
  const wrap = $('ownerList'); if(!wrap) return;
  const owners = STATE.meta?.owners || [];
  if(!owners.length){ wrap.innerHTML = '<div class="pcv-table-note">Aún no hay responsables capturados.</div>'; return; }
  wrap.innerHTML = owners.map(o=>`
    <div class="pcv-owner-item" data-owner-id="${o.id}">
      <div class="pcv-owner-top">
        <div class="pcv-owner-badge"><span class="pcv-owner-dot" style="background:${o.color_hex || '#d4af37'}"></span>${o.short_code || 'RESP'}</div>
        <button class="pcv-btn ghost" type="button" data-owner-save="${o.id}">Guardar</button>
      </div>
      <div class="pcv-owner-meta">
        <input class="pcv-input" data-owner-field="name" value="${(o.name||'').replace(/"/g,'&quot;')}">
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
          <input class="pcv-input" data-owner-field="short_code" value="${(o.short_code||'').replace(/"/g,'&quot;')}">
          <input class="pcv-input pcv-color" data-owner-field="color_hex" type="color" value="${o.color_hex || '#d4af37'}">
        </div>
        <input class="pcv-input" data-owner-field="phone" value="${(o.phone||'').replace(/"/g,'&quot;')}" placeholder="Teléfono">
        <input class="pcv-input" data-owner-field="email" value="${(o.email||'').replace(/"/g,'&quot;')}" placeholder="Correo">
        <input class="pcv-input" data-owner-field="notes" value="${(o.notes||'').replace(/"/g,'&quot;')}" placeholder="Notas">
      </div>
    </div>
  `).join('');
  wrap.querySelectorAll('[data-owner-save]').forEach(btn=>btn.addEventListener('click', async ()=>{
    const id = btn.getAttribute('data-owner-save');
    const box = wrap.querySelector(`[data-owner-id="${id}"]`);
    const body = {};
    box.querySelectorAll('[data-owner-field]').forEach(inp=>body[inp.getAttribute('data-owner-field')] = inp.value);
    await api(`/api/petroleum/control/owners/${id}`, {method:'PATCH', body: JSON.stringify(body)});
    toast('Responsable actualizado');
    await loadMeta();
  }));
}
function renderStations(){
  const body = $('stationOwnerTable'); if(!body) return;
  const stations = STATE.meta?.stations || [];
  const owners = STATE.meta?.owners || [];
  body.innerHTML = stations.map(s=>`
    <tr>
      <td>${s.station_number ? `<b>${s.station_number}</b> · ` : ''}${s.name || ''}</td>
      <td>
        <select class="pcv-input" data-station-owner="${s.id}">
          <option value="">Sin asignar</option>
          ${owners.map(o=>`<option value="${o.id}" ${String(o.id)===String(s.petroleum_owner_id||'')?'selected':''}>${o.short_code} · ${o.name}</option>`).join('')}
        </select>
      </td>
    </tr>
  `).join('');
  body.querySelectorAll('[data-station-owner]').forEach(sel=>sel.addEventListener('change', async ()=>{
    await api(`/api/petroleum/control/stations/${sel.getAttribute('data-station-owner')}/owner`, {method:'POST', body: JSON.stringify({owner_id: sel.value || null})});
    toast('Responsable asignado');
    await loadMeta();
    await loadEntries();
  }));
}
function renderDocTypes(){
  const docs = STATE.meta?.doc_types || [];
  const wrap = $('docTypeList'); if(wrap){ wrap.innerHTML = docs.map(d=>`<span class="pcv-chip" title="${(d.description||'').replace(/"/g,'&quot;')}"><span class="pcv-owner-dot" style="background:${d.accent_color || '#d4af37'}"></span>${d.icon || '•'} ${d.title}</span>`).join(''); }
  optList($('entryDocType'), docs, 'Selecciona documento', d=>(d.icon ? `${d.icon} ` : '') + (d.title || d.code));
  optList($('fltDocType'), docs, 'Todos', d=>(d.icon ? `${d.icon} ` : '') + (d.title || d.code));
}
function renderFilters(){
  const owners = STATE.meta?.owners || [];
  const stations = STATE.meta?.stations || [];
  optList($('fltOwner'), owners, 'Todos', o=>`${o.short_code} · ${o.name}`);
  optList($('fltStation'), stations, 'Todas', s=>`${s.station_number ? s.station_number + ' · ' : ''}${s.name}`);
  optList($('entryStation'), stations, 'Selecciona estación', s=>`${s.station_number ? s.station_number + ' · ' : ''}${s.name}`);
}
function fillEntryForm(item){
  $('entryId').value = item.id || '';
  $('entryStation').value = item.station_id || '';
  $('entryDocType').value = item.doc_type_id || '';
  $('entryStartDate').value = item.start_date || '';
  $('entryRenewalDate').value = item.renewal_date || '';
  $('entryDocStatus').value = item.document_status || 'vigente';
  $('entryPaymentStatus').value = item.payment_status || 'pendiente';
  $('entryLastPaymentDate').value = item.last_payment_date || '';
  $('entryAmountDue').value = item.amount_due ?? '';
  $('entryNotes').value = item.notes || '';
  window.scrollTo({top: document.querySelector('#entryForm').getBoundingClientRect().top + window.scrollY - 80, behavior:'smooth'});
}
function resetEntryForm(){ $('entryForm').reset(); $('entryId').value=''; $('entryPaymentStatus').value='pendiente'; $('entryDocStatus').value='vigente'; }
function renderEntries(){
  const body = $('controlTable'); if(!body) return;
  if(!STATE.entries.length){ body.innerHTML = '<tr><td colspan="10" class="pcv-table-note">No hay registros con los filtros actuales.</td></tr>'; return; }
  body.innerHTML = STATE.entries.map(it=>`
    <tr>
      <td>${it.owner_code ? `<span class="pcv-inline-owner"><span class="pcv-owner-dot" style="background:${it.owner_color || '#d4af37'}"></span>${it.owner_code}</span><div class="pcv-table-note" style="margin-top:6px;">${it.owner_name || ''}</div>` : '<span class="pcv-badge doc muted">Sin responsable</span>'}</td>
      <td><b>${it.station_number ? it.station_number + ' · ' : ''}${it.station_name || ''}</b><div class="pcv-table-note">${it.station_code || ''}</div></td>
      <td><span class="pcv-doc-label" title="${(it.doc_description || '').replace(/</g,'&lt;').replace(/"/g,'&quot;')}"><span class="pcv-doc-accent" style="background:${it.doc_color || '#d4af37'}"></span>${it.doc_icon || '•'} ${it.doc_title || ''}</span><div class="pcv-table-note" style="margin-top:6px;">${(it.doc_description || '').replace(/</g,'&lt;')}</div></td>
      <td>${it.start_date || '—'}</td>
      <td>${it.renewal_date || '—'}</td>
      <td>${badgeStatus('document_status', it.document_status, it.days_left)}</td>
      <td>${badgeStatus('payment_status', it.payment_status)}</td>
      <td>${badgeStatus('renewal_state', it.renewal_state, it.days_left)}</td>
      <td><div class="pcv-table-note">${(it.notes || '').replace(/</g,'&lt;')}</div></td>
      <td><button class="pcv-btn ghost" type="button" data-edit-entry="${it.id}">Editar</button></td>
    </tr>
  `).join('');
  body.querySelectorAll('[data-edit-entry]').forEach(btn=>btn.addEventListener('click', ()=>fillEntryForm(STATE.byId.get(Number(btn.getAttribute('data-edit-entry'))))));
}
async function loadMeta(){
  const data = await api('/api/petroleum/control/meta');
  STATE.meta = data;
  renderSummary(data.summary || {});
  renderOwners();
  renderStations();
  renderDocTypes();
  renderFilters();
}
async function loadEntries(){
  const qs = new URLSearchParams();
  [['owner_id', $('fltOwner')?.value], ['station_id', $('fltStation')?.value], ['doc_type_id', $('fltDocType')?.value], ['renewal_state', $('fltRenewal')?.value], ['payment_status', $('fltPayment')?.value]].forEach(([k,v])=>{ if(v) qs.set(k,v); });
  const data = await api('/api/petroleum/control/entries?' + qs.toString());
  STATE.entries = data.items || [];
  STATE.byId = new Map(STATE.entries.map(it=>[Number(it.id), it]));
  renderEntries();
}

document.addEventListener('DOMContentLoaded', async ()=>{
  try{
    await loadMeta();
    await loadEntries();
  }catch(err){ toast(err.message || 'No se pudo cargar el módulo'); }

  $('ownerForm')?.addEventListener('submit', async (e)=>{
    e.preventDefault();
    try{
      await api('/api/petroleum/control/owners', {method:'POST', body: JSON.stringify({
        name:$('ownerName').value, short_code:$('ownerCode').value, color_hex:$('ownerColor').value, phone:$('ownerPhone').value, email:$('ownerEmail').value, notes:$('ownerNotes').value
      })});
      toast('Responsable guardado');
      e.target.reset(); $('ownerColor').value='#d4af37';
      await loadMeta();
    }catch(err){ toast(err.message); }
  });

  $('docTypeForm')?.addEventListener('submit', async (e)=>{
    e.preventDefault();
    try{
      await api('/api/petroleum/control/doc-types', {method:'POST', body: JSON.stringify({
        code:$('docCode').value, title:$('docTitle').value, accent_color:$('docColor').value, sort_order:$('docSort').value
      })});
      toast('Documento agregado');
      e.target.reset(); $('docColor').value='#d4af37'; $('docSort').value='100';
      await loadMeta();
    }catch(err){ toast(err.message); }
  });

  $('entryForm')?.addEventListener('submit', async (e)=>{
    e.preventDefault();
    const id = $('entryId').value;
    const body = {
      station_id:$('entryStation').value, doc_type_id:$('entryDocType').value, start_date:$('entryStartDate').value, renewal_date:$('entryRenewalDate').value,
      document_status:$('entryDocStatus').value, payment_status:$('entryPaymentStatus').value, last_payment_date:$('entryLastPaymentDate').value,
      amount_due:$('entryAmountDue').value, notes:$('entryNotes').value
    };
    try{
      if(id){ await api(`/api/petroleum/control/entries/${id}`, {method:'PATCH', body: JSON.stringify(body)}); toast('Control actualizado'); }
      else { await api('/api/petroleum/control/entries', {method:'POST', body: JSON.stringify(body)}); toast('Control guardado'); }
      resetEntryForm();
      await loadMeta();
      await loadEntries();
    }catch(err){ toast(err.message); }
  });

  $('entryResetBtn')?.addEventListener('click', resetEntryForm);
  $('btnRefreshTable')?.addEventListener('click', ()=>loadEntries().catch(err=>toast(err.message)));
});
