(async()=>{
  const me = (await api('/api/me')).me;
  const isPetroleum = document.body.classList.contains('brand-petroleum');
  const actionsEl = qs('#panelActions');
  const miniStepsEl = qs('#panelMiniSteps');
  const statsEl = qs('#panelStats');

  // ---------------- icons (inline, theme-aware via currentColor) ----------------
  const ICONS = {
    bell: '<path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
    send: '<line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>',
    card: '<rect x="2" y="5" width="20" height="14" rx="2"/><line x1="2" y1="10" x2="22" y2="10"/>',
    alert: '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
    file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><polyline points="14 2 14 8 20 8"/><path d="M9 15l2 2 4-4"/>',
    calendar: '<rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>',
    shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="M9 12l2 2 4-4"/>',
    check: '<circle cx="12" cy="12" r="10"/><path d="M9 12l2 2 4-4"/>',
    download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
    login: '<path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/>',
    activity: '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
    inbox: '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11Z"/>',
    compass: '<circle cx="12" cy="12" r="10"/><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"/>',
    map: '<path d="M9 18l-6 3V5l6-3 6 3 6-3v16l-6 3-6-3Z"/><line x1="9" y1="2" x2="9" y2="18"/><line x1="15" y1="5" x2="15" y2="22"/>',
  };
  function icon(name){
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICONS[name] || ICONS.activity}</svg>`;
  }

  function tile(href, eyebrow, title, desc, iconName){
    return `<a class="action-tile" href="${href}"><div class="icon">${icon(iconName)}</div><div class="eyebrow">${_esc(eyebrow)}</div><div class="title">${_esc(title)}</div><div class="desc">${_esc(desc)}</div></a>`;
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
        ? [tile('/admin/document-deadlines','Admin','Control maestro','Vista global de documentos y renovaciones.','compass'), tile('/mod/document-renewals-calendar','Agenda','Vencimientos','Calendario de renovaciones y avisos.','calendar'), tile('/mod/notifications','Avisos','Notificaciones','Mensajes y recordatorios recientes.','bell'), tile('/admin/inbox','Revisión','Inbox admin','Pendientes para revisar y aprobar.','inbox')]
        : [tile('/admin/inbox','Revisión','Inbox admin','Pendientes para revisar y aprobar.','inbox'), tile('/admin/document-center','Documentos','Centro documental','Consulta documentos vigentes por estación.','file'), tile('/admin/sasisopa','Principal','SASISOPA','Documentos programados por estación.','shield'), tile('/admin/sgm','Principal','SGM','Seguimiento documental y operativo.','activity')];
      chips = isPetroleum
        ? [['1','Control maestro','/admin/document-deadlines'],['2','Vencimientos','/mod/document-renewals-calendar'],['3','Notificaciones','/mod/notifications']]
        : [['1','Inbox','/admin/inbox'],['2','Centro documental','/admin/document-center'],['3','SASISOPA / SGM','/admin/sasisopa']];
    } else if (isPetroleum){
      actions = [tile('/petroleum/normativas','Hoy','Normativas','Sube o actualiza documentos.','file'), tile('/petroleum/expedientes','Carpeta','Expediente normativo','Revisa faltantes y porcentaje.','shield'), tile('/mod/document-renewals-calendar','Avisos','Vencimientos','Consulta renovaciones cercanas.','calendar'), tile('/mod/notifications','Seguimiento','Notificaciones','Revisa tareas y recordatorios.','bell')];
      chips = [['1','Normativas','/petroleum/normativas'],['2','Expediente','/petroleum/expedientes'],['3','Vencimientos','/mod/document-renewals-calendar']];
    } else {
      actions = [tile('/staff/sasisopa','Hoy','SASISOPA','Consulta los documentos recibidos.','shield'), tile('/staff/sgm','Seguimiento','SGM','Revisa el seguimiento documental de tu estación.','activity'), tile('/mod/notifications','Avisos','Notificaciones','Revisa avisos y recordatorios.','bell'), tile('/mod/activities','Operación','Bitácora','Consulta actividades y pendientes del día.','calendar')];
      chips = [['1','Notificaciones','/mod/notifications'],['2','SASISOPA / SGM','/staff/sasisopa'],['3','Bitácora','/mod/activities']];
    }
    if (actionsEl) actionsEl.innerHTML = actions.join('');
    renderMiniSteps(chips);
  }

  // ---------------- hero greeting ----------------
  function greetingWord(){
    const h = new Date().getHours();
    if (h < 12) return 'Buenos días';
    if (h < 19) return 'Buenas tardes';
    return 'Buenas noches';
  }
  function roleLabel(role){
    const map = {
      admin: 'Administrador',
      operador: 'Operador',
      jefe_estacion: 'Jefe de estación',
      contador: 'Contador',
      auditor: 'Auditor',
    };
    return map[role] || role || '';
  }
  function renderHero(){
    const g = qs('#heroGreeting');
    const s = qs('#heroSub');
    if (g) g.textContent = `${greetingWord()}, ${me.username}`;
    if (s) s.textContent = `${roleLabel(me.role)} · ${isPetroleum ? 'PETROLEUM' : 'CONSULTING'} · Work Log`;
  }
  renderHero();

  renderGuide();

  // ---------------- stat cards + hero badge ----------------
  function statIcon(label){
    const map = {
      'No leídas': 'bell',
      'Entregas enviadas': 'send',
      'Pagos pendientes': 'card',
      'Alertas abiertas': 'alert',
      'Docs por revisar': 'file',
      'Docs pendientes': 'file',
      'Pendientes próximos': 'calendar',
      'Cumplimientos por vencer': 'shield',
    };
    return map[label] || 'activity';
  }

  const data = await api('/api/my/panel');
  const cards = (data.cards || []).map(c => ({
    l: c.label,
    v: c.value,
    tag: c.tone || 'ok',
    href: c.href || null
  }));

  const heroBadge = qs('#heroBadge');
  if (heroBadge && cards.length){
    const alerts = cards.filter(c => c.tag !== 'ok' && Number(c.v) > 0);
    heroBadge.hidden = false;
    if (!alerts.length){
      heroBadge.className = 'panel-hero-badge';
      heroBadge.innerHTML = `${icon('check')} Todo en orden`;
    } else {
      const worst = alerts.some(c => c.tag === 'bad') ? 'tone-bad' : 'tone-warn';
      heroBadge.className = 'panel-hero-badge ' + worst;
      const n = alerts.length;
      heroBadge.innerHTML = `${icon('alert')} ${n} ${n === 1 ? 'pendiente' : 'pendientes'} por revisar`;
    }
  }

  if (statsEl && cards.length){
    statsEl.hidden = false;
    statsEl.innerHTML = cards.map(c=>{
      const tone = c.tag === 'bad' ? 'tone-bad' : (c.tag === 'warn' ? 'tone-warn' : 'tone-ok');
      const tag = c.href ? 'a' : 'div';
      const hrefAttr = c.href ? ` href="${_esc(c.href)}"` : '';
      return `<${tag} class="stat-card ${tone}"${hrefAttr}>`
        + `<div class="icon">${icon(statIcon(c.l))}</div>`
        + `<div class="body"><div class="value">${_esc(String(c.v))}</div><div class="label">${_esc(c.l)}</div></div>`
        + `</${tag}>`;
    }).join('');
  }

  // ---------------- lists ----------------
  function fmtDate(s){
    s = String(s || '');
    const m = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
    return m ? `${m[3]}/${m[2]}/${m[1]}` : s;
  }
  function fmtDateTime(s){
    s = String(s || '');
    return s.replace('T', ' ').slice(0, 16);
  }
  function emptyState(msg){
    return `<div class="empty-state"><div class="icon">${icon('check')}</div><div>${_esc(msg)}</div></div>`;
  }

  const pending = (((data.lists||{}).pending_events)||[]);
  qs('#pendingList').innerHTML = pending.length
    ? pending.map(it=>`<div class="list-item"><div class="icon">${icon('calendar')}</div><div class="content"><div class="title">${_esc(it.title)}</div></div><div class="when">${_esc(fmtDate(it.start_date))}</div></div>`).join('')
    : emptyState('Sin pendientes próximos.');

  const notifs = (((data.lists||{}).notifications)||[]);
  qs('#notifList').innerHTML = notifs.length
    ? notifs.map(it=>`<div class="list-item"><div class="icon">${icon('bell')}</div><div class="content"><div class="title">${_esc(it.title)}</div>${it.body?`<div class="meta">${_esc(it.body)}</div>`:''}</div><div class="when">${_esc(fmtDateTime(it.created_at))}</div></div>`).join('')
    : emptyState('Sin notificaciones recientes.');

  // ---------------- audit (admin) ----------------
  function auditIcon(action){
    const a = String(action || '');
    if (a.startsWith('download')) return 'download';
    if (a.startsWith('login') || a.startsWith('logout')) return 'login';
    if (a.startsWith('send_notification')) return 'send';
    if (a.startsWith('create')) return 'check';
    return 'activity';
  }
  const audits = (((data.lists||{}).recent_audit)||[]);
  const auditEl = qs('#auditList');
  if (auditEl){
    auditEl.innerHTML = audits.length
      ? audits.map(it=>`<div class="list-item"><div class="icon">${icon(auditIcon(it.action))}</div><div class="content"><div class="title">${_esc(it.action)}</div><div class="meta">${_esc(it.entity||'')}${it.entity_id?` #${_esc(it.entity_id)}`:''}</div></div><div class="when">${_esc(fmtDateTime(it.created_at))}</div></div>`).join('')
      : emptyState('Sin movimientos recientes.');
  }
})();
