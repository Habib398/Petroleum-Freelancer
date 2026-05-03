(async ()=>{
  try{ await loadMe(); }catch(e){ /* ignore */ }

  const listEl = qs('#list');
  const sel = qs('#restoreSelect');
  const msg = qs('#msg');

  function humanSize(n){
    n = Number(n||0);
    const u = ['B','KB','MB','GB'];
    let i = 0;
    while(n>1024 && i<u.length-1){ n/=1024; i++; }
    return `${n.toFixed(i?1:0)} ${u[i]}`;
  }

  async function refresh(){
    const r = await api('/api/admin/backups');
    const items = r.items || [];
    if (!items.length){
      listEl.innerHTML = '<div class="empty"><div class="t">No hay backups</div><div class="d">Crea uno con el botón “Crear backup”.</div></div>';
      sel.innerHTML = '';
      return;
    }
    listEl.innerHTML = `
      <table class="table">
        <thead><tr><th>Archivo</th><th>Tamaño</th><th>Fecha</th><th></th></tr></thead>
        <tbody>
          ${items.map(it=>`
            <tr>
              <td><b>${_esc(it.name)}</b></td>
              <td>${humanSize(it.size)}</td>
              <td>${_esc(it.mtime)}</td>
              <td style="text-align:right;">
                <a class="btn small" href="/api/admin/backups/download/${encodeURIComponent(it.name)}">Descargar</a>
              </td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
    sel.innerHTML = items.map(it=>`<option value="${_esc(it.name)}">${_esc(it.name)} • ${humanSize(it.size)}</option>`).join('');
  }

  async function create(){
    msg.textContent = 'Creando backup…';
    await api('/api/admin/backups/create', { method:'POST', body: JSON.stringify({}) });
    msg.textContent = 'Backup creado.';
    await refresh();
  }

  async function restoreSelected(){
    const name = sel.value;
    const confirm = (qs('#confirm').value || '').trim();
    msg.textContent = '';
    const fd = new FormData();
    fd.append('name', name);
    fd.append('confirm', confirm);
    msg.textContent = 'Restaurando… (puede tardar)';
    await api('/api/admin/backups/restore', { method:'POST', body: fd, headers: {} });
    msg.textContent = 'Restauración completada. Recarga la página.';
  }

  async function restoreUpload(){
    const f = qs('#restoreFile').files[0];
    const confirm = (qs('#confirm').value || '').trim();
    if (!f){ msg.textContent='Selecciona un ZIP.'; return; }
    const fd = new FormData();
    fd.append('file', f);
    fd.append('confirm', confirm);
    msg.textContent = 'Restaurando ZIP…';
    await api('/api/admin/backups/restore', { method:'POST', body: fd, headers: {} });
    msg.textContent = 'Restauración completada. Recarga la página.';
  }

  qs('#btnRefresh').addEventListener('click', refresh);
  qs('#btnCreate').addEventListener('click', ()=> create().catch(e=>{ msg.textContent='Error al crear backup.'; }));
  qs('#btnRestore').addEventListener('click', ()=> restoreSelected().catch(e=>{ msg.textContent='Error al restaurar. Confirma RESTAURAR.'; }));
  qs('#btnRestoreUpload').addEventListener('click', ()=> restoreUpload().catch(e=>{ msg.textContent='Error al restaurar. Confirma RESTAURAR.'; }));

  await refresh();
})();
