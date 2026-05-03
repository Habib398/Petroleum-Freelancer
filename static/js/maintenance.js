(async ()=>{
  let me; try{ me=(await api("/api/me")).me; }catch(e){return;}
  const pumpT = qs("#pumpT");
  const pumpSel = qs("#pumpSel");
  const pumpErr = qs("#pumpErr");
  const mErr = qs("#mErr");

  const stationCard = qs("#maintStationCard");
  const stationSel = qs("#maintStation");
  let stations = [];
  let selectedStationId = null;
  const LS_KEY = `maint_station_${me.id}`;

  async function initStations(){
    try{
      const r = await api("/api/stations");
      stations = r.stations || [];
    }catch(e){ stations=[]; }
    if ((me.role === "admin" || me.role === "jefe_estacion") && stations.length > 1 && stationCard && stationSel){
      stationCard.hidden = false;
      stationSel.innerHTML = stations.map(s=>`<option value="${s.id}">${s.code} — ${s.name}</option>`).join("");
      const saved = localStorage.getItem(LS_KEY);
      const savedOk = saved && stations.some(s=>String(s.id)===String(saved));
      selectedStationId = Number(savedOk ? saved : stations[0].id);
      stationSel.value = String(selectedStationId);
      stationSel.addEventListener("change", async ()=>{
        selectedStationId = Number(stationSel.value);
        try{ localStorage.setItem(LS_KEY, String(selectedStationId)); }catch(_e){}
        await loadPumps();
        await refreshMaint();
      });
    } else if (stations.length) {
      selectedStationId = Number(stations[0].id);
    }
  }

  function pill(status){
    if(status==="green") return `<span class="pill green">Verde</span>`;
    if(status==="yellow") return `<span class="pill yellow">Amarillo</span>`;
    return `<span class="pill red">Rojo</span>`;
  }
  function fileLink(rel){
    if(!rel) return '<span class="muted">—</span>';
    return `<a href="/uploads/${rel}">Descargar</a>`;
  }

  async function loadPumps(){
    const url = (selectedStationId && (me.role === "admin" || me.role === "jefe_estacion"))
      ? `/api/pumps?station_id=${selectedStationId}`
      : "/api/pumps";
    const rows = (await api(url)).pumps || [];
    pumpT.innerHTML = rows.map(p=>`
      <tr><td><b>${p.pump_code}</b></td><td>${p.location||""}</td><td>${pill(p.status)}</td></tr>
    `).join("");
    pumpSel.innerHTML = `<option value="">(Sin bomba)</option>` + rows.map(p=>`<option value="${p.id}">${p.pump_code}</option>`).join("");
  }

  qs("#pumpAdd").addEventListener("click", async ()=>{
    pumpErr.hidden=true;
    try{
      const payload = {pump_code:qs("#pumpCode").value,location:qs("#pumpLoc").value};
      if (selectedStationId && (me.role === "admin" || me.role === "jefe_estacion")) payload.station_id = selectedStationId;
      await api("/api/pumps",{method:"POST",body:JSON.stringify(payload)});
      toast("Guardado","Bomba creada.");
      qs("#pumpCode").value=""; qs("#pumpLoc").value="";
      await loadPumps();
    }catch(e){
      pumpErr.textContent="Error: "+e.message;
      pumpErr.hidden=false;
    }
  });

  async function refreshMaint(){
    const url = (selectedStationId && (me.role === "admin" || me.role === "jefe_estacion"))
      ? `/api/maintenance?station_id=${selectedStationId}`
      : "/api/maintenance";
    const rows = (await api(url)).maintenance || [];
    const tb = qs("#mT");
    tb.innerHTML = rows.map(r=>`
      <tr>
        <td>${(r.created_at||"").slice(0,10)}</td>
        <td>${r.station_name||""}</td>
        <td>${r.kind}</td>
        <td>${r.pump_code||'<span class="muted">—</span>'}</td>
        <td class="muted">Antes: ${fileLink(r.evidence_before)}<br/>Después: ${fileLink(r.evidence_after)}</td>
      </tr>
    `).join("");
  }

  qs("#mForm").addEventListener("submit", async (ev)=>{
    ev.preventDefault();
    mErr.hidden=true;
    try{
      const fd = new FormData(ev.target);
      if (selectedStationId && (me.role === "admin" || me.role === "jefe_estacion")) fd.append("station_id", String(selectedStationId));
      await api("/api/maintenance",{method:"POST",body:fd,headers:{}});
      toast("Guardado","Mantenimiento registrado.");
      ev.target.reset();
      await refreshMaint();
    }catch(e){
      mErr.textContent="Error: "+e.message;
      mErr.hidden=false;
    }
  });

  await initStations();
  await loadPumps();
  await refreshMaint();
})();
