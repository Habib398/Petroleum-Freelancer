(async ()=>{
  // === TAB SWITCHING ===
  const tabs = qsa(".inbox-tab");
  tabs.forEach(tab => {
    tab.addEventListener("click", (e) => {
      e.preventDefault();
      const tabName = tab.dataset.tab;

      tabs.forEach(t => t.classList.remove("active"));
      qsa(".inbox-content").forEach(c => c.classList.remove("active"));

      tab.classList.add("active");
      const content = qs("#tab-" + tabName);
      if (content) content.classList.add("active");
    });
  });

  // === LOAD ESTACIONES ===
  try {
    const stationsData = await api("/api/stations");
    const stSel = qs("#fStation");
    if (stSel && stationsData && stationsData.stations) {
      const options = stationsData.stations.map(s => '<option value="' + s.id + '">' + s.code + ' - ' + s.name + '</option>');
      stSel.innerHTML = '<option value="">Todas</option>' + options.join("");
    }
  } catch (e) {
    console.error("Error loading stations:", e);
  }

  function setDefaultDates(){
    const now = new Date();
    const fTo = qs("#fTo");
    const fFrom = qs("#fFrom");
    if (fTo) fTo.value = now.toISOString().slice(0,10);
    if (fFrom) {
      const fromDt = new Date(now.getFullYear(), now.getMonth(), 1);
      fFrom.value = fromDt.toISOString().slice(0,10);
    }
  }
  setDefaultDates();

  function buildQuery(){
    const q = new URLSearchParams();
    const fStation = qs("#fStation");
    const fFrom = qs("#fFrom");
    const fTo = qs("#fTo");
    const fSev = qs("#fSev");
    const fAlertStatus = qs("#fAlertStatus");
    const fQ = qs("#fQ");

    if (fStation && fStation.value) q.set("station_id", fStation.value);
    if (fFrom && fFrom.value) q.set("from", fFrom.value);
    if (fTo && fTo.value) q.set("to", fTo.value);
    if (fSev && fSev.value) q.set("severity", fSev.value);
    if (fAlertStatus && fAlertStatus.value) q.set("alert_status", fAlertStatus.value);
    if (fQ && fQ.value) q.set("q", fQ.value);
    return q;
  }

  async function load(){
    try {
      const q = buildQuery();
      const data = await api("/api/admin/inbox?" + q.toString());

      // === KPI CARDS ===
      const kpis = qs("#inboxKpis");
      if (kpis) {
        const kpisData = data.kpis || {};
        const cards = [
          {l:"Pagos pendientes", v:kpisData.payments_pending||0, type:(kpisData.payments_pending?"warning":"success")},
          {l:"Alertas críticas", v:kpisData.red_alerts||0, type:(kpisData.red_alerts?"critical":"success")},
        ];
        let kpiHtml = "";
        cards.forEach(c => {
          const statusText = c.type === "critical" ? "Crítico" : (c.type === "warning" ? "Requiere Atención" : "OK");
          kpiHtml += '<div class="kpi-card ' + c.type + '">' +
            '<div class="kpi-label">' + c.l + '</div>' +
            '<div class="kpi-value">' + c.v + '</div>' +
            '<span class="kpi-status ' + c.type + '">' + statusText + '</span>' +
            '</div>';
        });
        kpis.innerHTML = kpiHtml;
      }

      // === ACTIVITY SUMMARY ===
      const actSummaryGrid = qs("#actSummaryGrid");
      if (actSummaryGrid && data.activity_overview){
        const stations = data.activity_overview.by_station || [];
        let gridHtml = "";
        if (stations.length === 0) {
          gridHtml = '<div style="grid-column: 1/-1; text-align: center; padding: 30px; color: var(--hme-text-soft);">Sin datos disponibles</div>';
        } else {
          stations.forEach(r => {
            gridHtml += '<div class="activity-summary-card">' +
              '<strong>' + (r.station_code||"") + '</strong>' +
              '<div class="stat">' +
                '<span style="color: var(--hme-success); font-weight: 700;">' + (r.done||0) + '</span> completadas' +
              '</div>' +
              '<div class="stat">' +
                '<span style="color: var(--hme-warning); font-weight: 700;">' + (r.pending||0) + '</span> pendientes' +
              '</div>';
            if (r.rejected) {
              gridHtml += '<div class="stat">' +
                '<span style="color: var(--hme-danger); font-weight: 700;">' + r.rejected + '</span> rechazadas' +
                '</div>';
            }
            gridHtml += '</div>';
          });
        }
        actSummaryGrid.innerHTML = gridHtml;
      }

      // === PAYMENTS TABLE ===
      const payT = qs("#payT");
      if (payT) {
        const payments = data.payments || [];
        let payHtml = "";
        if (payments.length === 0) {
          payHtml = '<tr><td colspan="4" style="text-align: center; padding: 30px; color: var(--hme-text-soft);">Sin pagos pendientes</td></tr>';
        } else {
          payments.forEach(p => {
            const proofLink = p.proof_path ? '<a class="btn-link" href="/uploads/' + p.proof_path + '">Comprobante</a>' : "—";
            payHtml += '<tr>' +
              '<td><strong>' + p.id + '</strong></td>' +
              '<td>' + (p.station_name||"") + '</td>' +
              '<td>' + proofLink + '</td>' +
              '<td style="font-size: 12px; color: var(--hme-text-soft);">Revisa en <b>Mensualidad</b></td>' +
              '</tr>';
          });
        }
        payT.innerHTML = payHtml;
      }

      // === ALERTS TABLE ===
      const alertT = qs("#alertT");
      if (alertT) {
        const alerts = data.alerts || [];
        let alertHtml = "";
        if (alerts.length === 0) {
          alertHtml = '<tr><td colspan="5" style="text-align: center; padding: 30px; color: var(--hme-text-soft);">Sin alertas</td></tr>';
        } else {
          alerts.forEach(a => {
            const severityColors = {
              "green": "ok",
              "yellow": "warn",
              "red": "bad"
            };
            const severityTag = severityColors[a.severity] || 'warn';
            alertHtml += '<tr>' +
              '<td><strong>' + a.id + '</strong></td>' +
              '<td>' + (a.station_name||"") + '</td>' +
              '<td><span class="tag ' + severityTag + '">' + a.severity + '</span></td>' +
              '<td><strong>' + a.title + '</strong></td>' +
              '<td>' + a.status + '</td>' +
              '</tr>';
          });
        }
        alertT.innerHTML = alertHtml;
      }

      // === STATION EVIDENCE TABLE (tab actividades) ===
      const actEv = qs("#actEvidenceT");
      const actEvCount = qs("#actEvidenceCount");
      if (actEv) {
        try {
          const evParams = new URLSearchParams();
          const _fSt = qs("#fStation"); if (_fSt && _fSt.value) evParams.set("station_id", _fSt.value);
          const _fFr = qs("#fFrom");  if (_fFr && _fFr.value) evParams.set("from", _fFr.value);
          const _fTo = qs("#fTo");    if (_fTo && _fTo.value) evParams.set("to", _fTo.value);
          const _fQ  = qs("#fQ");     if (_fQ  && _fQ.value)  evParams.set("q",  _fQ.value);

          const evData = await api("/api/station-evidence?" + evParams.toString());
          const items = evData.items || [];

          if (actEvCount) actEvCount.textContent = items.length ? "(" + items.length + ")" : "";

          if (items.length === 0) {
            actEv.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:30px;color:var(--hme-text-soft);">Sin evidencias para los filtros seleccionados.</td></tr>';
          } else {
            actEv.innerHTML = items.map(it => {
              const fecha = (it.event_date || it.created_at || "").slice(0, 10) || "—";
              const estacion = '<b>' + _esc(it.station_code || "") + '</b>' +
                (it.station_name ? ' • ' + _esc(it.station_name) : "");
              const actividad = it.event_id
                ? '<a class="btn-link" href="/mod/activities/event/' + it.event_id + '">' + _esc(it.activity_title || "Actividad") + '</a>'
                : _esc(it.activity_title || "—");
              const usuario = _esc(it.user_name || "—");
              const notas = _esc((it.notes || "").slice(0, 100)) || '<span style="color:var(--hme-text-soft)">—</span>';
              const archivo = it.evidence_path
                ? '<a class="btn ghost small" href="/uploads/' + encodeURIComponent(it.evidence_path) + '?inline=1" target="_blank" rel="noopener" style="margin-right:4px;">Ver</a>' +
                  '<a class="btn small" href="/uploads/' + encodeURIComponent(it.evidence_path) + '">Descargar</a>'
                : '—';
              return '<tr>' +
                '<td>' + fecha + '</td>' +
                '<td>' + estacion + '</td>' +
                '<td>' + actividad + '</td>' +
                '<td>' + usuario + '</td>' +
                '<td style="font-size:12px;color:var(--hme-text-soft);max-width:180px;">' + notas + '</td>' +
                '<td style="white-space:nowrap;">' + archivo + '</td>' +
                '</tr>';
            }).join("");
          }
        } catch (evErr) {
          const actEv2 = qs("#actEvidenceT");
          if (actEv2) actEv2.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:20px;color:var(--hme-danger);">Error al cargar evidencias.</td></tr>';
        }
      }
    } catch (e) {
      console.error("Error loading inbox data:", e);
      toast("Error", "No se pudieron cargar los datos del inbox: " + (e?.message || "error desconocido"));
    }
  }

  // === EVENT LISTENERS ===
  const fApply = qs("#fApply");
  if (fApply) fApply.addEventListener("click", load);

  const fClear = qs("#fClear");
  if (fClear) {
    fClear.addEventListener("click", () => {
      setDefaultDates();
      const fStation = qs("#fStation");
      const fSev = qs("#fSev");
      const fAlertStatus = qs("#fAlertStatus");
      const fQ = qs("#fQ");

      if (fStation) fStation.value = "";
      if (fSev) fSev.value = "";
      if (fAlertStatus) fAlertStatus.value = "";
      if (fQ) fQ.value = "";

      load();
    });
  }

  // Load on enter in search
  const fQ = qs("#fQ");
  if (fQ) {
    fQ.addEventListener("keypress", (e) => {
      if (e.key === "Enter") load();
    });
  }

  // Initial load
  await load();
})();
