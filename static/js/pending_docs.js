/* pending_docs.js – Lógica del módulo de documentos pendientes */

// Configuración inyectada desde Jinja2 vía window.PendingDocsConfig
const cfg = window.PendingDocsConfig || { isAdmin: false, defaultStationId: null, resetStationId: false };
const isAdmin = cfg.isAdmin;

function esc(s){ return String(s ?? '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])); }

async function api(url, opts={}){
  const r = await fetch(url, Object.assign({headers:{'Accept':'application/json'}}, opts));
  const j = await r.json().catch(()=>({ok:false,error:'invalid_json'}));
  if(!r.ok || !j.ok) throw new Error(j.message || j.error || ('HTTP '+r.status));
  return j;
}

function statusBadge(status){
  const s = String(status || 'pending').toLowerCase();
  return `<span class="badge ${esc(s)}">${esc(s === 'pending' ? 'Pendiente' : s === 'approved' ? 'Aprobado' : 'Rechazado')}</span>`;
}

async function reviewDoc(id, status){
  const comment = prompt(status === 'approved' ? 'Comentario opcional de aprobación:' : 'Motivo del rechazo o corrección requerida:') || '';
  try {
    await api(`/api/docs/pending/${id}/review`, {method:'POST', headers:{'Content-Type':'application/json','Accept':'application/json'}, body: JSON.stringify({status, review_comment: comment})});
    await loadDocs();
  } catch (err) {
    alert('No se pudo guardar la revisión: ' + err.message);
  }
}

async function loadDocs(){
  const q = encodeURIComponent(document.getElementById('q').value || '');
  const station = document.getElementById('stationFilter') ? encodeURIComponent(document.getElementById('stationFilter').value || '') : '';
  const status = encodeURIComponent(document.getElementById('statusFilter').value || '');
  const data = await api(`/api/docs/pending?station_id=${station}&status=${status}&q=${q}`);
  const rows = data.items || [];
  document.getElementById('msg').textContent = rows.length ? `${rows.length} documento(s)` : 'Sin envíos todavía.';
  const colspan = isAdmin ? 5 : 4;
  document.getElementById('tbody').innerHTML = rows.length ? rows.map(r => {
    const comment = r.review_comment ? `<div class="muted" style="margin-top:6px">Revisión: ${esc(r.review_comment)}</div>` : '';
    const note = r.change_reason ? `<div class="muted" style="margin-top:6px">Nota: ${esc(r.change_reason)}</div>` : '';
    const who = `<div class="muted">Subió: ${esc(r.created_by_name || '')} · ${esc(r.created_at || '')}</div>`;
    const reviewCell = isAdmin ? `<td><div class="actions"><button class="btnx warn" type="button" onclick="reviewDoc(${Number(r.id)}, 'approved')">Aprobar</button><button class="btnx bad" type="button" onclick="reviewDoc(${Number(r.id)}, 'rejected')">Rechazar</button></div></td>` : '';
    return `<tr>
      <td><div style="font-weight:800">${esc(r.title || 'Documento')}</div>${who}${note}${comment}</td>
      <td>${r.station_name ? esc(((r.station_code || '') + ' • ' + (r.station_name || '')).replace(/^\s*•\s*/, '')) : '<span class="muted">Sin estación</span>'}</td>
      <td>${statusBadge(r.status)}</td>
      <td><a href="${encodeURI('/uploads/' + String(r.file_path || '').replace(/\\/g,'/')}}" target="_blank" rel="noopener">Ver / descargar</a></td>
      ${reviewCell}
    </tr>`;
  }).join('') : `<tr><td colspan="${colspan}" class="muted">No hay documentos.</td></tr>`;
}

const btnRefresh = document.getElementById('btnRefresh'); if(btnRefresh) btnRefresh.addEventListener('click', loadDocs);
const q = document.getElementById('q'); if(q) q.addEventListener('keydown', e => { if(e.key==='Enter'){ e.preventDefault(); loadDocs(); } });
const stationFilter = document.getElementById('stationFilter'); if(stationFilter) stationFilter.addEventListener('change', loadDocs);
const statusFilter = document.getElementById('statusFilter'); if(statusFilter) statusFilter.addEventListener('change', loadDocs);

document.getElementById('uploadForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const msg = document.getElementById('uploadMsg');
  msg.textContent = 'Enviando…';
  try {
    await api('/api/docs/pending/upload', {method:'POST', body:fd});
    msg.textContent = 'Documento enviado a revisión.';
    e.target.reset();
    // Si el usuario no es admin y tiene solo una estación, restaurar el station_id oculto
    if(cfg.resetStationId && cfg.defaultStationId !== null){
      const stInput = e.target.querySelector('input[name="station_id"]');
      if(stInput) stInput.value = cfg.defaultStationId;
    }
    await loadDocs();
  } catch (err) {
    msg.textContent = 'No se pudo enviar: ' + err.message;
  }
});

loadDocs();
