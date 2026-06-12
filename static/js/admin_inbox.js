(async ()=>{
  const st = await api("/api/stations");
  const stSel = qs("#fStation");
  stSel.innerHTML = `<option value="">Todas</option>` + (st.stations||[]).map(s=>`<option value="${s.id}">${s.code} - ${s.name}</option>`).join("");

  function setDefaultDates(){
    const now = new Date();
    qs("#fTo").value = now.toISOString().slice(0,10);
    const fromDt = new Date(now.getFullYear(), now.getMonth(), 1);
    qs("#fFrom").value = fromDt.toISOString().slice(0,10);
  }
  setDefaultDates();

  function buildQuery(){
    const q = new URLSearchParams();
    const sid = qs("#fStation").value;
    const from = qs("#fFrom").value;
    const to = qs("#fTo").value;
    const sev = qs("#fSev").value;
    const ast = qs("#fAlertStatus").value;
    const ss = qs("#fSubStatus")?.value || "";
    const qq = qs("#fQ")?.value || "";
    if(sid) q.set("station_id", sid);
    if(from) q.set("from", from);
    if(to) q.set("to", to);
    if(sev) q.set("severity", sev);
    if(ast) q.set("alert_status", ast);
    if(ss) q.set("submission_status", ss);
    if(qq) q.set("q", qq);
    return q;
  }

  async function load(){
    const q = buildQuery();
    const k = await api("/api/admin/inbox?" + q.toString());

    const kpis = qs("#inboxKpis");
    const cards = [
      {l:"Entregas pendientes", v:k.kpis.submissions_pending, tag:(k.kpis.submissions_pending?"warn":"ok")},
      {l:"Pagos pendientes", v:k.kpis.payments_pending, tag:(k.kpis.payments_pending?"warn":"ok")},
      {l:"Alertas rojas abiertas", v:k.kpis.red_alerts, tag:(k.kpis.red_alerts?"bad":"ok")},
    ];
    kpis.innerHTML = cards.map(c=>`
      <div class="card kpi">
        <div><div class="l">${c.l}</div><div class="v">${c.v}</div></div>
        <div class="tag ${c.tag}">${c.tag==="bad"?"Crítico":c.tag==="warn"?"Atención":"OK"}</div>
      </div>`).join("");

    const subT = qs("#subT");
    subT.innerHTML = (k.submissions||[]).map(s=>{
      const st = s.status||"";
      const completed = st!=="rejected";
      const tag = completed ? "ok" : "bad";
      const stLabel = completed ? "Completada" : "Rechazada";
      const evLink = s.event_id ? `<a class="btn ghost small" href="/mod/activities/event/${s.event_id}">Ver</a>` : "";
      return `
      <tr>
        <td>${s.id}</td>
        <td>${(s.event_date||s.created_at||"-").slice(0,10)}</td>
        <td>${s.station_name||""}</td>
        <td>${s.activity_title||""}</td>
        <td>${s.user_name||""}</td>
        <td><span class="tag ${tag}">${stLabel}</span></td>
        <td>${s.evidence_path? `<a href="/uploads/${s.evidence_path}">Descargar</a>`:"—"}</td>
        <td>${evLink}</td>
      </tr>
    `;
    }).join("");

    const payT = qs("#payT");
    payT.innerHTML = (k.payments||[]).map(p=>`
      <tr>
        <td>${p.id}</td>
        <td>${p.station_name||""}</td>
        <td>${p.proof_path? `<a href="/uploads/${p.proof_path}">Descargar</a>`:"—"}</td>
        <td class="muted">Valida desde el módulo <b>Mensualidad</b> (adjunta factura).</td>
      </tr>
    `).join("");

    const alertT = qs("#alertT");
    alertT.innerHTML = (k.alerts||[]).map(a=>`
      <tr>
        <td>${a.id}</td>
        <td>${a.station_name||""}</td>
        <td>${a.severity}</td>
        <td><b>${a.title}</b></td>
        <td>${a.status}</td>
      </tr>
    `).join("");

    // Activities overview
    const actS = qs("#actSummaryT");
    const actM = qs("#actMissingT");
    if (actS && actM && k.activity_overview){
      actS.innerHTML = (k.activity_overview.by_station||[]).map(r=>`
        <tr>
          <td><b>${r.station_code||""}</b> ${r.station_name? "• "+r.station_name:""}</td>
          <td>${r.total}</td>
          <td>${r.done}</td>
          <td>${r.pending}</td>
          <td>${r.rejected}</td>
        </tr>
      `).join("");

      function freqLabel(x){
        const m={once:"Una vez",daily:"Diaria",weekly:"Semanal",monthly:"Mensual",bimonthly:"Bimestral",quarterly:"Trimestral",yearly:"Anual"};
        return m[x]||x||"—";
      }
      actM.innerHTML = (k.activity_overview.missing||[]).map(it=>`
        <tr>
          <td>${it.date}</td>
          <td><b>${it.station_code||""}</b> ${it.station_name? "• "+it.station_name:""}</td>
          <td>${it.activity_title||""}</td>
          <td>${freqLabel(it.repeat_kind)}</td>
          <td>${it.status==="rejected" ? "<span class=\"tag bad\">Rechazado</span>" : "<span class=\"tag warn\">Pendiente</span>"}</td>
        </tr>
      `).join("") || `<tr><td colspan="5" class="help">Sin pendientes en este rango 🎉</td></tr>`;
    }

  }

  qs("#fApply").addEventListener("click", load);
  qs("#fClear").addEventListener("click", ()=>{
    qs("#fStation").value="";
    qs("#fSev").value="";
    qs("#fAlertStatus").value="";
    if(qs("#fSubStatus")) qs("#fSubStatus").value="";
    if(qs("#fQ")) qs("#fQ").value="";
    setDefaultDates();
    load();
  });

  await load();
})();
