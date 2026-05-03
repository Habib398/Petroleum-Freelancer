(async()=>{
  const q = qs('#q');
  const station = qs('#station');
  const moduleEl = qs('#module');
  const urgency = qs('#urgency');
  const tbody = qs('#tbody');
  const kTotal = qs('#kTotal');
  const kSoon = qs('#kSoon');
  const kCrit = qs('#kCrit');
  const kOver = qs('#kOver');
  const MODULE_LABELS = {normativas:'Normativa', expediente_normativas:'Documento normativo'};

  function badge(txt, klass=''){ return txt ? `<span class="tag ${klass}">${_esc(txt)}</span>` : ''; }
  function moduleLabel(v){ return MODULE_LABELS[v] || (v||'').replaceAll('_',' '); }
  function stationOptions(items, selected=''){
    return ['<option value="">Todas</option>'].concat((items||[]).map(s=>`<option value="${s.id}" ${String(selected)===String(s.id)?'selected':''}>${_esc([s.code,s.name].filter(Boolean).join(' · '))}</option>`)).join('');
  }
  function rowTpl(r){
    const urgClass = r.urgency==='vencido' ? 'bad' : (['hoy','critico'].includes(r.urgency) ? 'warn' : 'ok');
    return `<tr>
      <td>${_esc(r.due_date||'')}</td>
      <td>${badge(r.urgency_label||r.urgency||'', urgClass)}</td>
      <td>${_esc(moduleLabel(r.module))}</td>
      <td>${_esc(r.scope_label||'')}</td>
      <td>${_esc(r.title||'')}</td>
      <td>${_esc(r.folio||'')}</td>
      <td>${badge((r.status||'').replaceAll('_',' '))}</td>
      <td>${_esc(r.responsible_name||'—')}</td>
      <td>${r.file_url ? `<a href="${_esc(r.file_url)}" target="_blank" rel="noopener">Ver</a>` : '<span class="help">Sin archivo</span>'}</td>
      <td><button class="btn tiny" data-renew="${r.id}">Renovar</button></td>
    </tr>`;
  }
  async function load(){
    const sp = new URLSearchParams({q:q.value||'', station_id:station.value||'', module:moduleEl.value||'', urgency:urgency.value||''});
    const r = await api('/api/document-deadlines?'+sp.toString());
    station.innerHTML = stationOptions(r.stations||[], station.value);
    kTotal.textContent = r.summary.total || 0;
    kSoon.textContent = r.summary.proximos || 0;
    kCrit.textContent = r.summary.criticos || 0;
    kOver.textContent = r.summary.vencidos || 0;
    tbody.innerHTML = (r.rows||[]).map(rowTpl).join('') || '<tr><td colspan="10" class="help">Sin resultados.</td></tr>';
    qsa('[data-renew]').forEach(btn=>btn.onclick=async()=>{
      const newDate = prompt('Nueva fecha de vencimiento (YYYY-MM-DD):');
      if(!newDate) return;
      try{
        await api('/api/document-deadlines/'+btn.dataset.renew+'/renew', {method:'POST', body: JSON.stringify({new_due_date:newDate})});
        toast('Renovación guardada');
        await load();
      }catch(e){ toast('No se pudo renovar', e.message||''); }
    });
  }
  qs('#reloadBtn').onclick = load;
  [q, station, moduleEl, urgency].forEach(el=>el && el.addEventListener('change', load));
  q.addEventListener('keyup', ()=>{ clearTimeout(window.__ddQ); window.__ddQ = setTimeout(load, 250); });
  await load();
})();
