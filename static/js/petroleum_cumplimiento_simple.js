/* Petroleum Cumplimiento: 3 docs (NOM-005, NOM-016, ANEXO 30-31) */

function csrfToken() {
  const el = document.querySelector('meta[name="csrf-token"]');
  return el ? el.getAttribute('content') : '';
}

async function apiFetch(url, options = {}) {
  const headers = options.headers || {};
  headers['X-CSRF-Token'] = csrfToken();
  return fetch(url, { ...options, headers });
}

function toast(msg) {
  const t = document.getElementById('pnToast');
  if (!t) return;
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(t._timer);
  t._timer = setTimeout(() => (t.hidden = true), 2800);
}

function formatMeta(item) {
  if (!item.has) return 'Sin archivo vigente';
  const f = item.file;
  const v = f.version ? `v${f.version}` : '';
  const when = f.uploaded_at ? String(f.uploaded_at).split(' ')[0] : '';
  const name = f.original_name || 'archivo';
  return `${v} • ${when} • ${name}`.trim();
}

function formatStatus(item) {
  const c = item && item.control;
  if (!c) return '<span class="pn-chip pn-chip-muted">Sin control administrativo</span>';
  const chips = [];
  const docMap = {
    vigente: ['pn-chip-ok', 'Documento vigente'],
    debe_documento: ['pn-chip-danger', 'Debe documento'],
    en_revision: ['pn-chip-warn', 'En revisión'],
    vencido: ['pn-chip-danger', 'Documento vencido'],
    no_aplica: ['pn-chip-muted', 'No aplica']
  };
  const payMap = {
    pagado: ['pn-chip-ok', 'Pago al corriente'],
    pendiente: ['pn-chip-warn', 'Pago pendiente'],
    vencido: ['pn-chip-danger', 'Pago vencido'],
    no_aplica: ['pn-chip-muted', 'Pago no aplica']
  };
  const renewMap = {
    vigente: ['pn-chip-ok', c.days_left == null ? 'Renovación vigente' : `Renueva en ${c.days_left} días`],
    proximo: ['pn-chip-warn', c.days_left == null ? 'Renovación próxima' : `Renueva en ${c.days_left} días`],
    vencido: ['pn-chip-danger', c.days_left == null ? 'Renovación vencida' : `Vencido ${Math.abs(c.days_left)} días`],
    sin_fecha: ['pn-chip-muted', 'Sin fecha de renovación']
  };
  const d = docMap[c.document_status] || ['pn-chip-muted', 'Documento'];
  const p = payMap[c.payment_status] || ['pn-chip-muted', 'Pago'];
  const r = renewMap[c.renewal_state] || ['pn-chip-muted', 'Renovación'];
  chips.push(`<span class="pn-chip ${d[0]}">${d[1]}</span>`);
  chips.push(`<span class="pn-chip ${p[0]}">${p[1]}</span>`);
  chips.push(`<span class="pn-chip ${r[0]}">${r[1]}</span>`);
  if (c.owner_code) {
    chips.push(`<span class="pn-chip pn-chip-owner"><span class="pn-chip-dot" style="background:${c.owner_color || '#d4af37'}"></span>${c.owner_code}</span>`);
  }
  return chips.join('');
}

let currentStationId = null;

async function loadStations() {
  const sel = document.getElementById('pnStation');
  if (!sel) return null;

  const res = await apiFetch('/api/stations', { method: 'GET' });
  const data = await res.json().catch(() => null);
  if (!res.ok || !data || !Array.isArray(data.stations)) {
    toast('No se pudieron cargar las estaciones');
    return null;
  }
  const stations = data.stations || [];
  sel.innerHTML = '';
  for (const s of stations) {
    const opt = document.createElement('option');
    opt.value = String(s.id);
    opt.textContent = `${s.station_number ? (s.station_number + ' • ') : ''}${s.name || ('Estación ' + s.id)}`;
    sel.appendChild(opt);
  }
  const saved = localStorage.getItem('pn_station_id');
  const exists = saved && stations.some((s) => String(s.id) === String(saved));
  sel.value = exists ? String(saved) : (stations[0] ? String(stations[0].id) : '');
  currentStationId = sel.value || null;
  if (currentStationId) localStorage.setItem('pn_station_id', String(currentStationId));

  sel.addEventListener('change', async () => {
    currentStationId = sel.value || null;
    if (currentStationId) localStorage.setItem('pn_station_id', String(currentStationId));
    await loadMeta();
  });

  return currentStationId;
}

async function loadMeta() {
  if (!currentStationId) {
    toast('Selecciona una estación');
    return;
  }
  const res = await apiFetch(`/api/petroleum/norms/meta?station_id=${encodeURIComponent(currentStationId)}`, { method: 'GET' });
  const data = await res.json().catch(() => null);
  if (!res.ok || !data || !data.ok) {
    toast('No se pudo cargar la información');
    return;
  }
  const byKey = {};
  for (const it of data.items || []) byKey[it.doc_key] = it;
  document.querySelectorAll('.pn-card[data-doc]').forEach((card) => {
    const key = card.getAttribute('data-doc');
    const metaEl = card.querySelector('[data-meta]');
    const preview = card.querySelector('[data-preview]');
    const download = card.querySelector('[data-download]');
    const statusEl = card.querySelector('[data-status]');
    const it = byKey[key] || { doc_key: key, has: false };
    if (metaEl) metaEl.textContent = formatMeta(it);
    if (statusEl) statusEl.innerHTML = formatStatus(it);
    if (preview) {
      preview.href = it.has && it.file && it.file.url ? `${it.file.url}?inline=1` : '#';
      preview.classList.toggle('pn-disabled', !it.has);
      preview.onclick = (e) => {
        if (!it.has) {
          e.preventDefault();
          toast('Aún no hay archivo para visualizar');
        }
      };
    }
    if (download) {
      download.href = it.has ? `/api/petroleum/norms/${key}/download?station_id=${encodeURIComponent(currentStationId)}` : '#';
      download.classList.toggle('pn-disabled', !it.has);
      download.onclick = (e) => {
        if (!it.has) {
          e.preventDefault();
          toast('Aún no hay archivo para descargar');
        }
      };
    }
  });
}

async function uploadDoc(docKey, file) {
  if (!currentStationId) {
    toast('Selecciona una estación');
    return;
  }
  const fd = new FormData();
  fd.append('file', file);
  fd.append('station_id', String(currentStationId));
  const res = await apiFetch(`/api/petroleum/norms/${docKey}/upload?station_id=${encodeURIComponent(currentStationId)}`, { method: 'POST', body: fd });
  const data = await res.json().catch(() => null);
  if (!res.ok || !data || !data.ok) {
    toast((data && (data.message || data.error)) || 'No se pudo subir el archivo');
    return;
  }
  toast(`Archivo actualizado (${docKey})`);
  await loadMeta();
}

function initUpload() {
  const canUpload = (document.querySelector('.pn-grid')?.getAttribute('data-can-upload') || '0') === '1';
  if (!canUpload) return;
  const fileInput = document.getElementById('pnFile');
  let currentKey = null;

  document.querySelectorAll('[data-upload]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const card = btn.closest('.pn-card');
      currentKey = card ? card.getAttribute('data-doc') : null;
      if (!currentKey) return;
      fileInput.value = '';
      fileInput.click();
    });
  });

  fileInput.addEventListener('change', async () => {
    const f = fileInput.files && fileInput.files[0];
    if (!f || !currentKey) return;
    const okExt = /(\.pdf|\.png|\.jpg|\.jpeg)$/i.test(f.name);
    if (!okExt) {
      toast('Formato no permitido (PDF/JPG/PNG)');
      return;
    }
    await uploadDoc(currentKey, f);
  });
}

document.addEventListener('DOMContentLoaded', async () => {
  await loadStations();
  await loadMeta();
  initUpload();
});
