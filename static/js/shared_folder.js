/* shared_folder.js – Lógica del módulo de carpeta compartida */

// Configuración inyectada desde Jinja2 vía window.SharedFolderConfig
const cfg = window.SharedFolderConfig || { folderModule: '', folderSection: '', resetStationId: false, defaultStationId: null };

function esc(s){ return String(s ?? '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])); }

async function api(url, opts={}){
  const r = await fetch(url, Object.assign({headers:{'Accept':'application/json'}}, opts));
  const j = await r.json().catch(()=>({ok:false,error:'invalid_json'}));
  if(!r.ok || !j.ok) throw new Error(j.message || j.error || ('HTTP '+r.status));
  return j;
}

async function loadDocs(){
  const q = encodeURIComponent(document.getElementById('q').value || '');
  const station = document.getElementById('stationFilter') ? encodeURIComponent(document.getElementById('stationFilter').value || '') : '';
  const data = await api(`/api/docs?module=${encodeURIComponent(cfg.folderModule)}&section=${encodeURIComponent(cfg.folderSection)}&station_id=${station}&q=${q}`);
  const rows = data.items || [];
  document.getElementById('msg').textContent = rows.length ? `${rows.length} archivo(s)` : 'Sin archivos todavía.';
  document.getElementById('tbody').innerHTML = rows.length ? rows.map(r => `
    <tr>
      <td><div style="font-weight:800">${esc(r.title || 'Documento')}</div><div class="muted">${esc(r.section || '')}</div></td>
      <td>${r.station_name ? esc(((r.station_code || '') + ' • ' + (r.station_name || '')).replace(/^\s*•\s*/, '')) : '<span class="muted">Sin estación</span>'}</td>
      <td>${esc(r.created_at || '')}</td>
      <td><a href="${encodeURI('/uploads/' + String(r.file_path || '').replace(/\\/g,'/'))}" target="_blank" rel="noopener">Ver / descargar</a></td>
    </tr>`).join('') : '<tr><td colspan="4" class="muted">No hay documentos.</td></tr>';
}

const btnRefresh = document.getElementById('btnRefresh'); if(btnRefresh) btnRefresh.addEventListener('click', loadDocs);
const q = document.getElementById('q'); if(q) q.addEventListener('keydown', e => { if(e.key==='Enter'){ e.preventDefault(); loadDocs(); } });
const stationFilter = document.getElementById('stationFilter'); if(stationFilter) stationFilter.addEventListener('change', loadDocs);

document.getElementById('uploadForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const msg = document.getElementById('uploadMsg');
  msg.textContent = 'Subiendo…';
  try {
    await api('/api/docs/upload', {method:'POST', body:fd});
    msg.textContent = 'Documento subido correctamente.';
    e.target.reset();
    if(cfg.resetStationId && cfg.defaultStationId !== null){
      const stInput = e.target.querySelector('input[name="station_id"]');
      if(stInput) stInput.value = cfg.defaultStationId;
    }
    await loadDocs();
  } catch (err) {
    msg.textContent = 'No se pudo subir: ' + err.message;
  }
});

loadDocs();
