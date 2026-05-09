(async()=>{
  const me = (await api('/api/me')).me;
  const isPetroleum = document.body.classList.contains('brand-petroleum');
  const actionsEl = qs('#panelActions');
  const miniStepsEl = qs('#panelMiniSteps');
  const kpiStripEl = qs('#panelKpiStrip');

  function tile(href, eyebrow, title, desc){
    return `<a class="action-tile" href="${href}"><div class="eyebrow">${_esc(eyebrow)}</div><div class="title">${_esc(title)}</div><div class="desc">${_esc(desc)}</div></a>`;
  }
  function stepChip(num, label, href){
    return `<a class="step-chip" href="${href}"><b>${num}</b><span>${_esc(label)}</span></a>`;
  }
  function renderMiniSteps(chips){
    if (!miniStepsEl) return;
    if (!chips || !chips.length){ miniStepsEl.hidden = true; miniStepsEl.innerHTML = ''; return; }
    miniStepsEl.hidden = false;
    const inner = chips.map((c, i)=>{
      const arrow = i < chips.length - 1 ? `<span class="arr">→</span>` : '';
      return stepChip(c[0], c[1], c[2]) + arrow;
    }).join('');
    miniStepsEl.innerHTML = `<span class="label">Empieza por:</span>${inner}`;
  }

  function renderGuide(){
    let actions = [];
    let chips = null;
    if (me.role === 'admin'){
      actions = isPetroleum
        ? [tile('/admin/document-deadlines','Admin','Control maestro','Vista global de documentos y renovaciones.'), tile('/mod/document-renewals-calendar','Agenda','Vencimientos','Calendario de renovaciones y avisos.'), tile('/mod/notifications','Avisos','Notificaciones','Mensajes y recordatorios recientes.'), tile('/admin/inbox','Revisión','Inbox admin','Pendientes para revisar y aprobar.')]
        : [tile('/admin/inbox','Revisión','Inbox admin','Pendientes para revisar y aprobar.'), tile('/admin/document-center','Documentos','Centro documental','Consulta documentos vigentes por estación.'), tile('/admin/sasisopa','Principal','SASISOPA','Documentos programados por estación.'), tile('/admin/sgm','Principal','SGM','Seguimiento documental y operativo.')];
      chips = isPetroleum
        ? [['1','Control maestro','/admin/document-deadlines'],['2','Vencimientos','/mod/document-renewals-calendar'],['3','Notificaciones','/mod/notifications']]
        : [['1','Inbox','/admin/inbox'],['2','Centro documental','/admin/document-center'],['3','SASISOPA / SGM','/admin/sasisopa']];
    } else if (isPetroleum){
      actions = [tile('/petroleum/normativas','Hoy','Normativas','Sube o actualiza documentos.'), tile('/petroleum/expedientes','Carpeta','Expediente normativo','Revisa faltantes y porcentaje.'), tile('/mod/document-renewals-calendar','Avisos','Vencimientos','Consulta renovaciones cercanas.'), tile('/mod/notifications','Seguimiento','Notificaciones','Revisa tareas y recordatorios.')];
      chips = [['1','Normativas','/petroleum/normativas'],['2','Expediente','/petroleum/expedientes'],['3','Vencimientos','/mod/document-renewals-calendar']];
    } else {
      actions = [tile('/staff/sasisopa','Hoy','SASISOPA','Consulta los documentos recibidos.'), tile('/staff/sgm','Seguimiento','SGM','Revisa el seguimiento documental de tu estación.'), tile('/mod/notifications','Avisos','Notificaciones','Revisa avisos y recordatorios.'), tile('/mod/activities','Operación','Bitácora','Consulta actividades y pendientes del día.')];
      chips = [['1','Notificaciones','/mod/notifications'],['2','SASISOPA / SGM','/staff/sasisopa'],['3','Bitácora','/mod/activities']];
    }
    if (actionsEl) actionsEl.innerHTML = actions.join('');
    renderMiniSteps(chips);
  }

  renderGuide();

  const data = await api('/api/my/panel');
  const cards = (data.cards || []).map(c => ({
    l: c.label,
    v: c.value,
    tag: c.tone || 'ok',
    href: c.href || null
  }));

  if (kpiStripEl && cards.length){
    const numericTotal = cards.filter(c => Number.isFinite(Number(c.v))).reduce((a,c)=>a+Number(c.v||0),0);
    const alerts = cards.filter(c => c.tag !== 'ok');
    const okOnes = cards.filter(c => c.tag === 'ok');
    const okPill = (c) => `<span class="kpi-pill"><b>${_esc(String(c.v))}</b> ${_esc(String(c.l||'').toLowerCase())}</span>`;
    const alertPill = (c) => {
      const cls = c.tag === 'bad' ? 'alert' : 'warn';
      const tag = c.href ? 'a' : 'span';
      const hrefAttr = c.href ? ` href="${_esc(c.href)}"` : '';
      return `<${tag} class="kpi-pill ${cls}"${hrefAttr}><b>${_esc(String(c.v))}</b> ${_esc(c.l)}</${tag}>`;
    };
    let html = '';
    if (!alerts.length){
      const statusLabel = numericTotal === 0 ? 'Todo en orden hoy' : 'Sin alertas';
      html = `<span class="kpi-status">✓ ${statusLabel}</span>` + okOnes.map(okPill).join(`<span class="sep"></span>`);
    } else {
      const okPart = okOnes.length ? `<span class="sep"></span>` + okOnes.map(okPill).join(`<span class="sep"></span>`) : '';
      html = alerts.map(alertPill).join('') + okPart;
    }
    kpiStripEl.hidden = false;
    kpiStripEl.innerHTML = html;
  }

  const pending = (((data.lists||{}).pending_events)||[]);
  qs('#pendingList').innerHTML = pending.length ? pending.map(it=>`<div style="margin-bottom:8px"><b>${_esc(it.title)}</b><div>${_esc(it.start_date||'')}</div></div>`).join('') : 'Sin pendientes próximos.';

  const notifs = (((data.lists||{}).notifications)||[]);
  qs('#notifList').innerHTML = notifs.length ? notifs.map(it=>`<div style="margin-bottom:8px"><b>${_esc(it.title)}</b><div>${_esc(it.body||'')}</div><div class="help">${_esc(it.created_at||'')}</div></div>`).join('') : 'Sin notificaciones recientes.';

  const audits = (((data.lists||{}).recent_audit)||[]);
  const auditEl = qs('#auditList');
  if (auditEl){
    auditEl.innerHTML = audits.length ? audits.map(it=>`<div style="margin-bottom:8px"><b>${_esc(it.action)}</b> • ${_esc(it.entity||'')} #${_esc(it.entity_id||'')}<div class="help">${_esc(it.created_at||'')}</div></div>`).join('') : 'Sin movimientos recientes.';
  }
})();
