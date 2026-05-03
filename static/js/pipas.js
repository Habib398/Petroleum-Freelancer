(async ()=>{
  let me; try{ me=(await api("/api/me")).me; }catch(e){return;}
  const tbody = qs("#pTbody");
  const err = qs("#pErr");
  const form = qs("#pForm");

  const stationRow = qs("#pStationRow");
  const stationSel = qs("#pStation");
  let stations = [];
  let selectedStationId = null;
  const LS_KEY = `pipas_station_${me.id}`;

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

  function fileLink(rel){
    if(!rel) return '<span class="muted">—</span>';
    return `<a href="/uploads/${rel}">Descargar</a>`;
  }

  async function refresh(){
    const rows = (await api("/api/pipas")).pipas || [];
    const filtered = (selectedStationId && (me.role === "admin" || me.role === "jefe_estacion"))
      ? rows.filter(r=>Number(r.station_id)===Number(selectedStationId))
      : rows;
    tbody.innerHTML = filtered.map(r=>`
      <tr>
        <td>${(r.created_at||"").slice(0,10)}</td>
        <td>${r.station_name||""}</td>
        <td><span class="pill gray">${r.fuel_type}</span></td>
        <td><b>${Number(r.liters||0).toFixed(2)}</b></td>
        <td class="muted">
          Ticket: ${fileLink(r.ticket_path)}<br/>
          Factura: ${fileLink(r.factura_path)}<br/>
          Antes: ${fileLink(r.before_path)}<br/>
          Después: ${fileLink(r.after_path)}
        </td>
      </tr>
    `).join("");
  }

  form.addEventListener("submit", async (ev)=>{
    ev.preventDefault();
    err.hidden=true;
    try{
      const fd = new FormData(form);
      await api("/api/pipas",{method:"POST",body:fd,headers:{}});
      toast("Guardado","Pipa registrada.");
      form.reset();
      await refresh();
    }catch(e){
      err.textContent="Error: "+e.message;
      err.hidden=false;
    }
  });

  await initStations();
  await refresh();
})();
