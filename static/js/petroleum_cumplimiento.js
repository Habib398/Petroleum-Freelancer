let ME = null;
let CURRENT_CODE = null;
let ITEMS = {}; // code -> item

function statusToDotClass(st){
  if (st === 'approved') return 'ok';
  if (st === 'in_review') return 'review';
  if (st === 'rejected') return 'bad';
  return '';
}

function openDrawer(){
  const d = document.getElementById('drawer');
  if (!d) return;
  d.classList.add('open');
  d.setAttribute('aria-hidden','false');
}

function closeDrawer(){
  const d = document.getElementById('drawer');
  if (!d) return;
  d.classList.remove('open');
  d.setAttribute('aria-hidden','true');
}

async function refreshStatuses(){
  const station_id = document.getElementById('stationSel').value;
  const r = await api(`/api/compliance/items?station_id=${encodeURIComponent(station_id)}`);
  ITEMS = {};
  (r.items || []).forEach(it => { ITEMS[it.code] = it; });
  document.querySelectorAll('.dot').forEach(dot => {
    dot.classList.remove('ok','review','bad');
    const code = dot.getAttribute('data-dot');
    const it = ITEMS[code];
    const cls = statusToDotClass(it ? it.status : 'pending');
    if (cls) dot.classList.add(cls);
  });
}

function renderVersions(files){
  const wrap = document.getElementById('versions');
  const hint = document.getElementById('versionsHint');
  if (!wrap) return;
  const list = (files || []);
  hint.textContent = list.length ? `${list.length} archivo(s)` : 'Sin archivos aún';
  if (!list.length){
    wrap.innerHTML = `<div class="muted">Aún no hay evidencias. Sube un PDF/JPG/PNG para generar la versión 1.</div>`;
    return;
  }
  const rows = list.map(f => {
    const when = f.uploaded_at ? new Date(f.uploaded_at.replace(' ', 'T')) : null;
    const dt = when ? when.toLocaleString() : '';
    return `
      <div class="vrow">
        <div class="top">
          <div>
            <div class="name">v${f.version} • ${escapeHtml(f.original_name || 'archivo')}</div>
            <div class="meta">${dt}</div>
          </div>
          <div style="display:flex;gap:10px;align-items:center;">
            <a href="${f.url}" target="_blank" rel="noopener">Ver/Descargar</a>
          </div>
        </div>
      </div>
    `;
  }).join('');
  wrap.innerHTML = `<div class="versions">${rows}</div>`;
}

function escapeHtml(s){
  return (s||'').toString()
    .replaceAll('&','&amp;')
    .replaceAll('<','&lt;')
    .replaceAll('>','&gt;')
    .replaceAll('"','&quot;')
    .replaceAll("'",'&#039;');
}

async function openItem(code){
  CURRENT_CODE = code;
  const station_id = document.getElementById('stationSel').value;
  const r = await api(`/api/compliance/item/${encodeURIComponent(code)}?station_id=${encodeURIComponent(station_id)}`);
  const it = r.item;
  document.getElementById('drawerCode').textContent = (it.section || 'PETROLEUM').toUpperCase();
  document.getElementById('drawerTitle').textContent = it.title;
  document.getElementById('drawerDesc').textContent = it.description || '';
  document.getElementById('statusSel').value = it.status || 'pending';
  document.getElementById('statusNote').value = it.status_note || '';
  renderVersions(r.files || []);
  openDrawer();
}

async function saveStatus(){
  if (!CURRENT_CODE) return;
  const station_id = document.getElementById('stationSel').value;
  const status = document.getElementById('statusSel').value;
  const note = document.getElementById('statusNote').value;
  await api(`/api/compliance/item/${encodeURIComponent(CURRENT_CODE)}/status`, {
    method: 'POST',
    body: JSON.stringify({ station_id, status, note })
  });
  toast('Guardado', 'Estatus actualizado');
  await refreshStatuses();
}

async function uploadEvidence(){
  if (!CURRENT_CODE) return;
  const station_id = document.getElementById('stationSel').value;
  const inp = document.getElementById('fileInp');
  if (!inp.files || !inp.files[0]){ toast('Falta archivo','Selecciona un archivo'); return; }
  const fd = new FormData();
  fd.append('file', inp.files[0]);
  fd.append('station_id', station_id);
  const r = await api(`/api/compliance/item/${encodeURIComponent(CURRENT_CODE)}/upload`, { method:'POST', body: fd });
  toast('Subido', `Versión v${r.version}`);
  inp.value = '';
  await openItem(CURRENT_CODE);
  await refreshStatuses();
}

async function init(){
  ME = await loadMe();
  setActiveNav();
  initTheme();

  // Close drawer handlers
  document.getElementById('drawerClose').addEventListener('click', closeDrawer);
  document.getElementById('drawerBackdrop').addEventListener('click', closeDrawer);

  // Hotspots
  document.querySelectorAll('.hotspot').forEach(btn => {
    btn.addEventListener('click', () => openItem(btn.getAttribute('data-code')));
  });

  document.getElementById('stationSel').addEventListener('change', async () => {
    await refreshStatuses();
    closeDrawer();
  });
  document.getElementById('saveStatusBtn').addEventListener('click', saveStatus);
  document.getElementById('uploadBtn').addEventListener('click', uploadEvidence);

  await refreshStatuses();
}

document.addEventListener('DOMContentLoaded', init);
