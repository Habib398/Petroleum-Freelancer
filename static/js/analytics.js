(async ()=>{
  const me = (await api("/api/me")).me;
  const stSel = qs("#anStation");

  async function loadStations(){
    const s = await api("/api/stations");
    const stations = s.stations || [];
    stSel.innerHTML = "";
    if(["admin","auditor"].includes(me.role)){
      stSel.innerHTML += `<option value="">Todas</option>`;
      for(const x of stations){
        stSel.innerHTML += `<option value="${x.id}">${x.code} - ${x.name}</option>`;
      }
    } else {
      const mine = stations.find(x=>String(x.id)===String(me.station_id));
      if(mine) stSel.innerHTML = `<option value="${mine.id}">${mine.code} - ${mine.name}</option>`;
      else stSel.innerHTML = `<option value="${me.station_id||""}">Mi estación</option>`;
    }
  }

  function setDefaultDates(){
    const now = new Date();
    const to = now.toISOString().slice(0,10);
    const fromDt = new Date(now.getFullYear(), now.getMonth(), 1);
    const from = fromDt.toISOString().slice(0,10);
    qs("#anFrom").value = from;
    qs("#anTo").value = to;
  }

  let litersChart, statusChart;

  function buildCharts(payload){
    const labels = payload.series.map(r=>r.label);
    const magna = payload.series.map(r=>r.magna);
    const premium = payload.series.map(r=>r.premium);
    const diesel = payload.series.map(r=>r.diesel);

    const ctx = qs("#litersChart").getContext("2d");
    if(litersChart) litersChart.destroy();
    litersChart = new Chart(ctx, {
      type: "line",
      data: { labels, datasets: [
        {label:"Magna", data: magna},
        {label:"Premium", data: premium},
        {label:"Diésel", data: diesel},
      ]},
      options: { responsive:true, plugins:{legend:{position:"bottom"}} }
    });

    const st = payload.status;
    const ctx2 = qs("#statusChart").getContext("2d");
    if(statusChart) statusChart.destroy();
    statusChart = new Chart(ctx2, {
      type: "bar",
      data: {
        labels: ["Activas","Modo vista","Vencidas","Alertas rojas"],
        datasets: [{label:"Total", data:[st.active, st.view_only, st.expired, st.red_alerts]}]
      },
      options: { responsive:true, plugins:{legend:{display:false}} }
    });
  }

  async function refresh(){
    const station_id = stSel.value;
    const from = qs("#anFrom").value;
    const to = qs("#anTo").value;
    const group = qs("#anGroup").value;
    const q = new URLSearchParams();
    if(station_id) q.set("station_id", station_id);
    if(from) q.set("from", from);
    if(to) q.set("to", to);
    q.set("group", group);

    const payload = await api("/api/analytics/liters?"+q.toString());
    buildCharts(payload);

    const base = "/api/export/analytics_liters";
    qs("#anExportCsv").href = base + ".csv?" + q.toString();
    qs("#anExportXlsx").href = base + ".xlsx?" + q.toString();
  }

  await loadStations();
  setDefaultDates();
  qs("#anRefresh").addEventListener("click", refresh);
  await refresh();
})();
