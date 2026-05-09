(async ()=>{
  let me = null;
  try { me = (await api("/api/me")).me; } catch(e){ return; }

  const kpiStripEl = qs("#kpiStrip");
  const miniStepsEl = qs("#miniSteps");
  const quickEl = qs("#quick");
  const stBox = qs("#stationBox");
  const isPetroleum = document.body.classList.contains("brand-petroleum");
  const activityLabel = isPetroleum ? "Agenda" : "Actividades";
  const quickActionsEl = qs("#quickActions");
  const pageTitle = qs("#pageTitle");
  const pageSub = qs("#pageSub");
  const staffSimple = qs("#staffSimple");
  const staffSummary = qs("#staffSummary");
  const todayTasksEl = qs("#todayTasks");
  const docBoardEl = qs("#docBoard");
  const renewalListEl = qs("#renewalList");
  const notificationListEl = qs("#notificationList");
  const primaryModuleBtn = qs("#primaryModuleBtn");

  function actionTile(href, eyebrow, title, desc){
    return `<a class="action-tile" href="${href}"><div class="eyebrow">${_esc(eyebrow)}</div><div class="title">${_esc(title)}</div><div class="desc">${_esc(desc)}</div></a>`;
  }
  function summaryCard(eyebrow, value, meta, tone, footer=""){
    return `<div class="card summary-card"><div class="eyebrow">${_esc(eyebrow)}</div><div class="value">${_esc(String(value ?? 0))}</div><div class="meta">${_esc(meta || "")}</div><div class="footer">${_esc(footer || "")}</div><div class="tag ${tone||"ok"}" style="align-self:flex-start;">${tone==="bad"?"Crítico":tone==="warn"?"Atención":"OK"}</div></div>`;
  }
  function taskRow(idx, title, desc){
    return `<div class="task-item"><b>${idx}</b><div><div class="title">${_esc(title)}</div><div class="desc">${_esc(desc)}</div></div></div>`;
  }
  function renewalRow(item){
    const when = item?.due_date || item?.date || "Sin fecha";
    const urgency = item?.urgency ? String(item.urgency).replaceAll("_"," ") : "programado";
    const tone = urgency.includes("venc") ? "bad" : (urgency.includes("crit") || urgency.includes("próx") || urgency.includes("prox")) ? "warn" : "ok";
    return `<a class="soft-item" href="${_esc(item?.url || "/mod/document-renewals-calendar")}" style="text-decoration:none;color:inherit;display:block;"><div style="display:flex;align-items:flex-start;justify-content:space-between;gap:10px;"><div><div style="font-weight:900;">${_esc(item?.title || "Documento")}</div><div class="helper-note">${_esc(item?.scope_label || item?.station_name || "Tu estación")} · ${_esc(when)}</div></div><span class="tag ${tone}">${_esc(urgency)}</span></div></a>`;
  }
  function noteRow(item){
    return `<div class="soft-item"><div style="font-weight:800;">${_esc(item?.title || "Aviso")}</div><div class="helper-note">${_esc(item?.body || "")}</div><div class="helper-note">${_esc(item?.created_at || "")}</div></div>`;
  }
  function docBoardTemplate(cfg){
    const pct = Math.max(0, Math.min(100, Number(cfg?.pct || 0)));
    return `<div class="doc-progress"><div><div style="display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;"><div style="font-weight:900;font-size:24px;">${pct}%</div><span class="tag ${pct>=95?"ok":pct>=60?"warn":"bad"}">${pct>=95?"Completo":pct>=60?"En proceso":"Pendiente"}</span></div><div class="bar" style="margin-top:8px;"><span style="width:${pct}%;"></span></div><div class="helper-note" style="margin-top:8px;">${_esc(cfg?.hint || "Sube primero lo faltante y luego revisa vencimientos.")}</div></div><div class="doc-grid"><div class="doc-mini"><b>${_esc(String(cfg?.missing ?? 0))}</b><span>Faltantes obligatorios</span></div><div class="doc-mini"><b>${_esc(String(cfg?.soon ?? 0))}</b><span>Próximos a vencer</span></div><div class="doc-mini"><b>${_esc(String(cfg?.bad ?? 0))}</b><span>Vencidos</span></div></div><div style="display:flex;gap:10px;flex-wrap:wrap;"><a class="btn primary" href="${_esc(cfg?.primaryHref || "/staff/menu")}">${_esc(cfg?.primaryLabel || "Abrir módulo")}</a><a class="btn ghost" href="/mod/document-renewals-calendar">Ver vencimientos</a></div></div>`;
  }
  function stepChip(num, label, href){
    return `<a class="step-chip" href="${href}"><b>${num}</b><span>${_esc(label)}</span></a>`;
  }
  function renderMiniSteps(chips){
    if (!miniStepsEl) return;
    if (!chips || !chips.length){ miniStepsEl.hidden = true; miniStepsEl.innerHTML = ""; return; }
    miniStepsEl.hidden = false;
    const inner = chips.map((c, i)=>{
      const arrow = i < chips.length - 1 ? `<span class="arr">→</span>` : "";
      return stepChip(c[0], c[1], c[2]) + arrow;
    }).join("");
    miniStepsEl.innerHTML = `<span class="label">Empieza por:</span>${inner}`;
  }
  function renderGuide(){
    const brand = isPetroleum ? "petroleum" : "consulting";
    let actions = [];
    let chips = null;
    if (me.role === "admin"){
      if (pageTitle) pageTitle.textContent = brand === "petroleum" ? "Panel de control Petroleum" : "Panel de control Consulting";
      if (pageSub) pageSub.textContent = "Resumen operativo y accesos rápidos para supervisión.";
      actions = brand === "petroleum"
        ? [actionTile('/petroleum/normativas','Principal','Normativas','Captura y sigue requisitos técnicos por estación.'), actionTile('/petroleum/expedientes','Carpeta','Expediente normativo','Revisa documentos faltantes y vigencias.'), actionTile('/mod/document-renewals-calendar','Agenda','Vencimientos','Consulta renovaciones próximas en calendario.'), actionTile('/admin/document-deadlines','Admin','Control maestro','Vista global de documentos por vencer o renovar.')]
        : [actionTile('/admin/sasisopa','Principal','SASISOPA','Revisa documentos y programación por estación.'), actionTile('/admin/sgm','Carpeta','SGM','Da seguimiento documental y operativo.'), actionTile('/admin/inbox','Revisión','Inbox admin','Atiende pendientes y envíos por revisar.'), actionTile('/admin/document-center','Admin','Centro documental','Consulta documentos cargados por estación y versión vigente.')];
      chips = brand === "petroleum"
        ? [["1","Normativas","/petroleum/normativas"],["2","Expediente","/petroleum/expedientes"],["3","Vencimientos","/mod/document-renewals-calendar"]]
        : [["1","SASISOPA","/admin/sasisopa"],["2","SGM","/admin/sgm"],["3","Inbox / Centro documental","/admin/inbox"]];
    } else if (["jefe_estacion","operador"].includes(me.role)){
      if (pageTitle) pageTitle.textContent = "Inicio de hoy";
      if (pageSub) pageSub.textContent = brand === "petroleum" ? "Haz primero tus capturas, revisa faltantes y atiende vencimientos de tu estación." : "Consulta tus avisos y entra solo al módulo documental que el administrador haya asignado a tu estación.";
      actions = brand === "petroleum"
        ? [actionTile('/petroleum/normativas','Hoy','Normativas','Sube, corrige o revisa documentos de tu estación.'), actionTile('/petroleum/expedientes','Carpeta','Expediente normativo','Mira faltantes y porcentaje de cumplimiento.'), actionTile('/mod/document-renewals-calendar','Avisos','Vencimientos','Consulta qué documentos debes renovar pronto.'), actionTile('/mod/notifications','Seguimiento','Notificaciones','Revisa avisos y tareas pendientes.')]
        : [actionTile('/staff/sasisopa','Hoy','SASISOPA','Consulta los documentos recibidos de tu estación.'), actionTile('/staff/sgm','Seguimiento','SGM','Revisa el seguimiento documental de tu estación.'), actionTile('/mod/notifications','Avisos','Notificaciones','Consulta avisos del administrador.'), actionTile('/mod/activities','Operación','Bitácora','Revisa actividades y pendientes del día.')];
      chips = null;
    } else {
      if (pageTitle) pageTitle.textContent = "Dashboard";
      if (pageSub) pageSub.textContent = "Resumen operativo y accesos rápidos.";
      actions = [actionTile('/mod/operational-calendar','Agenda','Calendario operativo','Revisa actividades, vencimientos y próximos eventos.'), actionTile('/mod/notifications','Avisos','Notificaciones','Consulta mensajes y recordatorios.'), actionTile('/mod/reports','Consulta','Reportes','Genera reportes y revisa información resumida.'), actionTile('/mod/profile','Cuenta','Perfil','Actualiza tus datos y firma.')];
      chips = [["1","Calendario operativo","/mod/operational-calendar"],["2","Notificaciones","/mod/notifications"],["3","Reportes","/mod/reports"]];
    }
    quickActionsEl.innerHTML = actions.join('');
    renderMiniSteps(chips);
  }

  async function renderStaffHome(stations){
    if (!["jefe_estacion","operador"].includes(me.role) || !staffSimple) return;
    staffSimple.hidden = false;
    const legacyOps = qs("#legacyOps");
    const activityCard = qs("#activityProgress");
    if (legacyOps) legacyOps.hidden = true;
    if (activityCard) activityCard.hidden = true;
    const stationId = Number(selectedStationId || me.station_id || (stations[0] && stations[0].id) || 0) || null;
    const focusCard = qs("#stationFocus");
    if (focusCard && me.role !== "admin") focusCard.hidden = true;
    const primaryHref = isPetroleum ? "/petroleum/normativas" : "/staff/sasisopa";
    const primaryLabel = isPetroleum ? "Abrir Normativas" : "Abrir SASISOPA";
    if (primaryModuleBtn){ primaryModuleBtn.href = primaryHref; primaryModuleBtn.textContent = primaryLabel; }

    let panel = {cards:[], lists:{}};
    try { panel = await api("/api/my/panel"); } catch(_e){}
    let renewals = {items:[], summary:{}};
    try {
      const today = new Date();
      const to = new Date(today.getTime() + 1000*60*60*24*30);
      const fromIso = today.toISOString().slice(0,10);
      const toIso = to.toISOString().slice(0,10);
      const qsx = new URLSearchParams({from:fromIso,to:toIso});
      if (stationId) qsx.set("station_id", String(stationId));
      renewals = await api(`/api/document-renewals-calendar?${qsx.toString()}`);
    } catch(_e){}

    let docs = null;
    if (isPetroleum){
      try {
        const ex = await api(`/api/expedientes/items?area=normativas&station_id=${encodeURIComponent(String(stationId||""))}`);
        const summary = ex.summary || {};
        const weights = {vigente:1.0,no_aplica:1.0,proximo_a_vencer:0.85,en_revision:0.6,vencido:0,faltante:0};
        const scored = (ex.items||[]).filter(i => Number(i.is_required||0)===1);
        const base = scored.length ? scored : (ex.items||[]);
        const score = base.reduce((acc,i)=> acc + (weights[String(i.computed_status||i.status||"faltante")] ?? 0), 0);
        const pct = base.length ? Math.round((score/base.length)*100) : 0;
        docs = { pct, missing: Number(summary.required_missing||0), soon: Number(summary.proximo_a_vencer||0), bad: Number(summary.vencido||0), hint: pct >= 95 ? "Tu expediente normativo está al día." : "Completa faltantes y corrige vencidos para subir tu porcentaje.", primaryHref, primaryLabel };
      } catch(_e){}
    } else {
      docs = { pct: 0, missing: 0, soon: 0, bad: 0, hint: "Los anexos y documentos de Consulting los carga el administrador y tu estación solo consulta los que le corresponden.", primaryHref, primaryLabel };
    }

    const pendingEvents = panel?.lists?.pending_events || [];
    const notes = panel?.lists?.notifications || [];
    const unread = Number((panel?.cards || []).find(c => c.label === "No leídas")?.value || 0);
    const soonDue = Number(renewals?.summary?.soon || renewals?.summary?.proximo_a_vencer || 0);
    const overdue = Number(renewals?.summary?.overdue || renewals?.summary?.vencido || 0);
    const docsMissing = Number(docs?.missing || 0);

    if (staffSummary){
      staffSummary.innerHTML = [
        summaryCard("Pendientes de hoy", pendingEvents.length, pendingEvents.length ? `Tienes ${pendingEvents.length} actividad(es) sin evidencia en los próximos 14 días.` : "No hay actividades pendientes cercanas.", pendingEvents.length ? "warn" : "ok", isPetroleum ? "Revisa Agenda y Normativas." : "Revisa Actividades, SASISOPA o SGM."),
        summaryCard("Documentos faltantes", docsMissing, docsMissing ? "Aún faltan obligatorios por subir o corregir." : "Tu carpeta no tiene faltantes obligatorios.", docsMissing ? "bad" : "ok", docs?.pct!=null ? `Avance actual: ${docs.pct}%` : ""),
        summaryCard("Vencimientos próximos", soonDue + overdue, overdue ? `Incluye ${overdue} vencido(s).` : "No hay vencimientos críticos inmediatos.", (soonDue + overdue) ? (overdue ? "bad" : "warn") : "ok", unread ? `${unread} aviso(s) sin leer.` : "Sin avisos urgentes.")
      ].join("");
    }

    if (todayTasksEl){
      const step2Title = isPetroleum ? "Actualiza Normativas" : "Consulta documentos asignados";
      const step2Desc = isPetroleum ? "Captura, corrige o valida registros técnicos de tu estación." : "El administrador carga los anexos; tu estación solo consulta los documentos que le corresponden.";
      const step3Title = docsMissing ? "Completa faltantes" : "Revisa vencimientos";
      const step3Desc = docsMissing ? `Te faltan ${docsMissing} documento(s) obligatorio(s).` : ((soonDue + overdue) ? `Tienes ${soonDue + overdue} documento(s) para revisar por fecha.` : "Tu expediente va al día. Solo revisa avisos y agenda.");
      todayTasksEl.innerHTML = [
        taskRow(1, isPetroleum ? "Revisa tu agenda y pendientes" : "Revisa tu agenda y pendientes", pendingEvents.length ? `Tienes ${pendingEvents.length} actividad(es) próximas sin evidencia.` : "No tienes actividades urgentes para hoy."),
        taskRow(2, step2Title, step2Desc),
        taskRow(3, step3Title, step3Desc)
      ].join("");
    }

    if (docBoardEl){
      docBoardEl.innerHTML = docs ? docBoardTemplate(docs) : `<div class="empty-inline">No se pudo cargar el estado documental en este momento.</div>`;
    }

    if (renewalListEl){
      const items = (renewals?.items || []).slice(0, 6);
      renewalListEl.innerHTML = items.length ? items.map(renewalRow).join("") : `<div class="empty-inline">No tienes vencimientos próximos en los siguientes 30 días.</div>`;
    }

    if (notificationListEl){
      notificationListEl.innerHTML = notes.length ? notes.slice(0, 6).map(noteRow).join("") : `<div class="empty-inline">No tienes avisos recientes.</div>`;
    }
  }

  const stationsResp = await api("/api/stations");
  const stations = stationsResp.stations || [];
  renderGuide();

  // helpers
  function barRow(label, d){
    const pct = d.pct || 0;
    return `
      <div style="display:grid;grid-template-columns:140px 1fr 110px;gap:10px;align-items:center;margin:10px 0;">
        <div style="font-weight:900;">${label}</div>
        <div style="height:12px;border-radius:999px;background:rgba(2,6,23,.10);overflow:hidden;">
          <div style="height:100%;width:${pct}%;background:var(--hme-primary);"></div>
        </div>
        <div class="help" style="text-align:right;"><b>${d.done}</b> / ${d.total} • ${pct}%</div>
      </div>
    `;
  }

  // ---------------- KPIs (tira compacta) ----------------
  const cards = [];
  if (["jefe_estacion","operador"].includes(me.role)) {
    if (kpiStripEl) kpiStripEl.hidden = true;
  } else if (me.role === "admin") {
    const inbox = await api("/api/admin/inbox");
    const k = inbox.kpis;
    cards.push({l:"Entregas pendientes", v:k.submissions_pending, tag:(k.submissions_pending? "warn":"ok"), href:"/admin/inbox"});
    cards.push({l:"Pagos pendientes", v:k.payments_pending, tag:(k.payments_pending? "warn":"ok"), href:"/admin/inbox"});
    cards.push({l:"Alertas rojas", v:k.red_alerts, tag:(k.red_alerts? "bad":"ok"), href:"/mod/alerts"});
    cards.push({l:"SASISOPA por revisar", v:(k.sasisopa_pending||0), tag:((k.sasisopa_pending||0)? "warn":"ok"), href:"/admin/sasisopa"});
    cards.push({l:"SGM por revisar", v:(k.sgm_pending||0), tag:((k.sgm_pending||0)? "warn":"ok"), href:"/admin/sgm"});
    cards.push({l:"Calibraciones incompletas", v:(k.calibraciones_incompletas||0), tag:((k.calibraciones_incompletas||0)? "warn":"ok"), href:"/admin/calibraciones"});
  } else {
    if (me.role !== "operador") {
      cards.push({l:"Mensualidad", v:(me.monthly_status || "active"), tag:(me.monthly_status==="active"?"ok":"warn")});
    }
    cards.push({l:"Estaciones", v:(stations.length || 0), tag:"ok"});
    cards.push({l:"Rol", v:me.role, tag:"ok"});
  }

  if (kpiStripEl && cards.length){
    const numericTotal = cards.filter(c => Number.isFinite(Number(c.v))).reduce((a,c)=>a+Number(c.v||0),0);
    const alerts = cards.filter(c => c.tag !== "ok");
    const okOnes = cards.filter(c => c.tag === "ok");
    const okPill = (c) => `<span class="kpi-pill"><b>${_esc(String(c.v))}</b> ${_esc(c.l.toLowerCase())}</span>`;
    const alertPill = (c) => `<a class="kpi-pill ${c.tag==="bad"?"alert":"warn"}" href="${_esc(c.href||"#")}"><b>${_esc(String(c.v))}</b> ${_esc(c.l)}</a>`;
    let html = "";
    if (!alerts.length){
      const statusLabel = numericTotal === 0 && me.role === "admin" ? "Todo en orden hoy" : "Sin alertas";
      html = `<span class="kpi-status">✓ ${statusLabel}</span>` + okOnes.map(okPill).join(`<span class="sep"></span>`);
    } else {
      const okPart = okOnes.length ? `<span class="sep"></span>` + okOnes.map(okPill).join(`<span class="sep"></span>`) : "";
      html = alerts.map(alertPill).join("") + okPart;
    }
    kpiStripEl.hidden = false;
    kpiStripEl.innerHTML = html;
  }

  // La "Bandeja rápida" del bloque legacyOps repetía exactamente estos KPIs para admin → se oculta.
  if (me.role === "admin") {
    const legacyOps = qs("#legacyOps");
    if (legacyOps) legacyOps.hidden = true;
  }

  // ---------------- Quick ----------------
  if (["jefe_estacion","operador"].includes(me.role)) {
    const legacyOps = qs("#legacyOps");
    if (legacyOps) legacyOps.hidden = true;
  } else if (me.role === "admin") {
    // Admin: la tira KPI y el inbox ya cubren esta info. legacyOps queda oculto arriba.
  } else if (quickEl) {
    quickEl.innerHTML = `
      <div>Gestiona tu operación desde <b>${activityLabel}</b> y sube evidencias completas.</div>
      <div class="help" style="margin-top:8px;">Tip: si una evidencia es rechazada, vuelve a subirla para que se marque tu avance.</div>
    `;
  }

  // ---------------- Station box + selectors ----------------
  let selectedStationId = null;
  let selectedStation = null;

  const LS_KEY = `dash_station_${me.id}`;

  function setSelectedStation(id){
    selectedStationId = id ? Number(id) : null;
    selectedStation = stations.find(s=>Number(s.id)===Number(selectedStationId)) || null;
    if (selectedStation) {
      stBox.innerHTML = `
        <div><b>${selectedStation.name}</b> (${selectedStation.code})</div>
        <div>${selectedStation.city || ""} ${selectedStation.state ? "• "+selectedStation.state : ""}</div>
        ${me.role==="operador" ? "" : `<div>Status mensualidad: <b>${selectedStation.monthly_status}</b></div>`}
        ${selectedStation.group_name ? `<div class="help">Grupo: <b>${selectedStation.group_name}</b></div>` : ""}
      `;
    } else {
      stBox.innerHTML = (me.role==="admin")
        ? `Admin: puedes ver todas las estaciones y sus módulos.`
        : `Sin estación asignada.`;
    }
  }

  // default selection
  if (stations.length) {
    const saved = localStorage.getItem(LS_KEY);
    const savedOk = saved && stations.some(s=>String(s.id)===String(saved));
    setSelectedStation(savedOk ? saved : stations[0].id);
  }
  await renderStaffHome(stations);

  // ---------------- Station focus card (admin + jefe_estacion) ----------------
  const focusCard = qs("#stationFocus");
  const focusSelect = qs("#stationSelect");
  const focusBody = qs("#stationFocusBody");
  const overdueTag = qs("#stationOverdue");

  async function renderFocus(){
    if (!focusBody || !selectedStationId) return;
    const p = await api(`/api/station/activity-progress?station_id=${selectedStationId}`);
    // overdue tag
    if (overdueTag){
      if ((p.overdue||0) > 0){
        overdueTag.style.display = "";
        overdueTag.textContent = `Vencidas: ${p.overdue}`;
      } else {
        overdueTag.style.display = "none";
      }
    }
    focusBody.innerHTML = `
      <div class="help">Hoy: <b>${p.today}</b></div>
      ${barRow("Diarias", p.daily)}
      ${barRow("Mensual", p.monthly)}
      ${barRow("Anual", p.yearly)}
      <div class="help" style="margin-top:10px;">Se marca avance cuando hay evidencia <b>enviada/aprobada</b>. Vencidas = eventos pasados sin evidencia válida.</div>
    `;
  }

  if (focusCard && focusSelect && (me.role === "admin" || me.role === "jefe_estacion")) {
    focusCard.hidden = false;
    focusSelect.innerHTML = stations.map(s=>`<option value="${s.id}">${s.code} — ${s.name}</option>`).join("");
    if (selectedStationId) focusSelect.value = String(selectedStationId);

    focusSelect.addEventListener("change", async (e)=>{
      setSelectedStation(e.target.value);
      try{ localStorage.setItem(LS_KEY, String(e.target.value)); }catch(_e){}
      await renderFocus();
    });

    // initial render
    await renderFocus();
  }

  // ---------------- Activity progress (operador + roles con una sola estación) ----------------
  if (me.role !== "admin") {
    const card = qs("#activityProgress");
    const body = qs("#activityProgressBody");

    // Si es jefe con múltiples estaciones, usamos la vista por estación (focus) y ocultamos este resumen duplicado.
    if (me.role === "jefe_estacion" && stations.length > 1) {
      if (card) card.hidden = true;
      return;
    }

    if (card && body) {
      if (staffSimple && !staffSimple.hidden) { card.hidden = true; return; }
      try {
        // si ya hay selección, pedimos por estación; si no, el endpoint de "my" funciona
        let p = null;
        if (selectedStationId && (me.role === "jefe_estacion")) {
          p = await api(`/api/station/activity-progress?station_id=${selectedStationId}`);
        } else {
          p = await api("/api/my/activity-progress");
        }
        card.hidden = false;

        body.innerHTML = `
          <div class="help">Hoy: <b>${p.today}</b></div>
          ${barRow("Diarias", p.daily)}
          ${barRow("Mensual", p.monthly)}
          ${barRow("Anual", p.yearly)}
          <div class="help" style="margin-top:10px;">Se marca avance cuando <b>subes evidencia</b> (enviado/aprobado). Si el admin rechaza, se contará como pendiente.</div>
        `;
      } catch (e) {
        // keep hidden
      }
    }
  }
})();
