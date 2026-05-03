(async()=>{
  const me = (await api('/api/me')).me;
  const isPetroleum = document.body.classList.contains('brand-petroleum');
  const guideTitle = qs('#panelGuideTitle');
  const guideText = qs('#panelGuideText');
  const guideSteps = qs('#panelGuideSteps');
  const actionsEl = qs('#panelActions');

  function tile(href, eyebrow, title, desc){
    return `<a class="action-tile" href="${href}"><div class="eyebrow">${_esc(eyebrow)}</div><div class="title">${_esc(title)}</div><div class="desc">${_esc(desc)}</div></a>`;
  }
  function renderGuide(){
    let steps = [];
    let actions = [];
    if (me.role === 'admin'){
      guideTitle.textContent = 'Atajos administrativos';
      guideText.textContent = 'Desde aquí salta a revisión, vencimientos y supervisión global.';
      steps = ['Abre el control maestro si quieres revisar todo lo que vence.', 'Abre notificaciones para atender avisos nuevos.', 'Usa el calendario si buscas renovaciones por fecha.'];
      actions = isPetroleum ? [tile('/admin/document-deadlines','Admin','Control maestro','Vista global de documentos y renovaciones.'), tile('/mod/document-renewals-calendar','Agenda','Vencimientos','Calendario de renovaciones y avisos.'), tile('/mod/notifications','Avisos','Notificaciones','Mensajes y recordatorios recientes.'), tile('/admin/inbox','Revisión','Inbox admin','Pendientes para revisar y aprobar.')] : [tile('/admin/inbox','Revisión','Inbox admin','Pendientes para revisar y aprobar.'), tile('/admin/document-center','Documentos','Centro documental','Consulta documentos vigentes por estación.'), tile('/admin/sasisopa','Principal','SASISOPA','Documentos programados por estación.'), tile('/admin/sgm','Principal','SGM','Seguimiento documental y operativo.')];
    } else if (isPetroleum){
      guideTitle.textContent = 'Atajos para tu estación';
      guideText.textContent = 'Usa estos accesos para subir, revisar y renovar documentos sin perderte.';
      steps = ['Normativas para capturar o corregir.', 'Expediente para revisar faltantes.', 'Vencimientos para saber qué renovar primero.'];
      actions = [tile('/petroleum/normativas','Hoy','Normativas','Sube o actualiza documentos.'), tile('/petroleum/expedientes','Carpeta','Expediente normativo','Revisa faltantes y porcentaje.'), tile('/mod/document-renewals-calendar','Avisos','Vencimientos','Consulta renovaciones cercanas.'), tile('/mod/notifications','Seguimiento','Notificaciones','Revisa tareas y recordatorios.')];
    } else {
      guideTitle.textContent = 'Atajos para tu estación';
      guideText.textContent = 'Usa estos accesos para revisar avisos y entrar al módulo documental asignado sin perderte.';
      steps = ['Revisa notificaciones del administrador.', 'Entra a SASISOPA o SGM según tu documento asignado.', 'Consulta dashboard y actividades para tus pendientes del día.'];
      actions = [tile('/staff/sasisopa','Hoy','SASISOPA','Consulta los documentos recibidos.'), tile('/staff/sgm','Seguimiento','SGM','Revisa el seguimiento documental de tu estación.'), tile('/mod/notifications','Avisos','Notificaciones','Revisa avisos y recordatorios.'), tile('/mod/activities','Operación','Bitácora','Consulta actividades y pendientes del día.')];
    }
    if (guideSteps) guideSteps.innerHTML = steps.map((s,i)=>`<div class="step"><b>${i+1}</b><span>${_esc(s)}</span></div>`).join('');
    if (actionsEl) actionsEl.innerHTML = actions.join('');
  }

  renderGuide();
  const data = await api('/api/my/panel');
  const cards = data.cards || [];
  qs('#cards').innerHTML = cards.map(c=>`
    <div class="card kpi"><div><div class="l">${_esc(c.label)}</div><div class="v">${_esc(c.value)}</div></div><div class="tag ${c.tone||'ok'}">${_esc((c.tone||'ok').toUpperCase())}</div></div>
  `).join('');

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
