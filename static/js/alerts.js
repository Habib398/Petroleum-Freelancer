(async ()=>{
  let me; try{ me=(await api("/api/me")).me; }catch(e){return;}
  const tb = qs("#aT");
  const err = qs("#aErr");

  const stationRow = qs("#aStationRow");
  const stationSel = qs("#aStation");
  let stations = [];
  let selectedStationId = null;
  const LS_KEY = `alerts_station_${me.id}`;

  async function initStations(){
    try{
      const r = await api("/api/stations");
      stations = r.stations || [];
    }catch(e){ stations=[]; }
    if ((me.role === "admin" || me.role === "jefe_estacion") && stations.length > 1 && stationRow && stationSel){
      stationRow.hidden = false;
      stationSel.innerHTML = stations.map(s=>`<option value="${s.id}">${s.code} — ${s.name}</option>`).join("");
      const saved = localStorage.getItem(LS_KEY);
      const savedOk = saved && stations.some(s=>String(s.id)===String(saved));
      selectedStationId = Number(savedOk ? saved : stations[0].id);
      stationSel.value = String(selectedStationId);
      stationSel.addEventListener("change", async ()=>{
        selectedStationId = Number(stationSel.value);
        try{ localStorage.setItem(LS_KEY, String(selectedStationId)); }catch(_e){}
        await refresh();
      });
    } else if (stations.length) {
      selectedStationId = Number(stations[0].id);
    }
  }

  function sevPill(sev){
    if(sev==="green") return `<span class="pill green">Verde</span>`;
    if(sev==="yellow") return `<span class="pill yellow">Amarilla</span>`;
    return `<span class="pill red">Roja</span>`;
  }
  async function refresh(){
    const url = (selectedStationId && (me.role === "admin" || me.role === "jefe_estacion"))
      ? `/api/alerts?station_id=${selectedStationId}`
      : "/api/alerts";
    const rows = (await api(url)).alerts || [];
    tb.innerHTML = rows.map(r=>`
      <tr>
        <td>${(r.created_at||"").slice(0,10)}</td>
        <td>${r.station_name||""}</td>
        <td>${sevPill(r.severity)}</td>
        <td><b>${r.title}</b><div class="muted">${r.description||""}</div></td>
        <td>${r.status==="open"?'<span class="pill yellow">Abierta</span>':'<span class="pill gray">Cerrada</span>'}</td>
        <td>${(r.status==="open" && (me.role==="admin"||me.role==="jefe_estacion"))? `<button class="btn ghost small" data-close="${r.id}">Cerrar</button>`:""}</td>
      </tr>
    `).join("");
    qsa("[data-close]").forEach(b=>b.addEventListener("click", async ()=>{
      await api(`/api/alerts/${b.dataset.close}/close`,{method:"POST"});
      toast("Listo","Alerta cerrada.");
      await refresh();
    }));
  }

  qs("#aSave").addEventListener("click", async ()=>{
    err.hidden=true;
    try{
      const payload = {severity:qs("#aSev").value,title:qs("#aTitle").value,description:qs("#aDesc").value};
      if (selectedStationId && (me.role === "admin" || me.role === "jefe_estacion")) payload.station_id = selectedStationId;
      await api("/api/alerts",{method:"POST",body:JSON.stringify(payload)});
      toast("Guardado","Alerta creada.");
      qs("#aTitle").value=""; qs("#aDesc").value="";
      await refresh();
    }catch(e){
      err.textContent="Error: "+e.message;
      err.hidden=false;
    }
  });

  await initStations();
  await refresh();
})();
