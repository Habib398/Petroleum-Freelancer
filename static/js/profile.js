(async ()=>{
  let me; try{ me=(await api("/api/me")).me; }catch(e){return;}
  const state = qs("#profState");
  const ok = qs("#profOk");
  const err = qs("#profErr");
  const form = qs("#profileForm");
  const stationWrap = qs("#profileStationWrap");
  const stationSel = qs("#profileStation");

  const canSelectStation = ["admin","contador","auditor"].includes(me.role);
  const canEdit = me.role === "admin";

  if (canSelectStation && stationWrap && stationSel){
    stationWrap.hidden = false;
    try{
      const data = await api("/api/stations");
      const stations = data.stations || [];
      stationSel.innerHTML = `<option value="">Selecciona una estación…</option>` +
        stations.map(s=>`<option value="${s.id}">${s.code} • ${s.name}</option>`).join("");
      if (me.station_id) stationSel.value = String(me.station_id);
      if (!stationSel.value && stations.length===1) stationSel.value = String(stations[0].id);
      stationSel.addEventListener("change", ()=> load());
    }catch(_e){}
  }

  if (!canEdit) {
    qsa("input,select,textarea,button", form).forEach(el=>{
      if (el === stationSel) return;
      if (el.type === "file") { el.closest("div")?.setAttribute("hidden",""); el.hidden=true; }
      else { el.setAttribute("disabled",""); }
    });
    const btn = qs("button[type=submit]", form);
    if (btn) btn.hidden = true;
    const help = qs(".help", form.parentElement);
    if (help) help.textContent = canSelectStation ? "Solo consulta. Selecciona la estación para ver FIEL y razón social." : "Solo lectura. Información de estación y responsable.";
  }

  function selectedStationId(){
    if (stationSel && stationSel.value) return stationSel.value;
    return me.station_id || "";
  }

  async function load(){
    ok.hidden=true; err.hidden=true;
    const sid = selectedStationId();
    const url = sid ? `/api/profile?station_id=${encodeURIComponent(sid)}` : "/api/profile";
    const r = await api(url);
    const p = r.profile;
    if (canEdit && stationSel){
      form.station_id.value = sid || "";
    }
    if (p){
      form.permit_number.value = p.permit_number || "";
      form.legal_name.value = p.legal_name || "";
      state.innerHTML = `
        <div>Permiso: <b>${p.permit_number||"—"}</b></div>
        <div>Razón social: <b>${p.legal_name||"—"}</b></div>
        <div>FIEL actualizada: <b>${(p.fiel_updated_at||"").slice(0,10) || "—"}</b></div>
      `;
    }else{
      form.permit_number.value = "";
      form.legal_name.value = "";
      state.textContent = sid ? "Sin datos aún para la estación seleccionada." : "Selecciona una estación.";
    }
  }

  form.addEventListener("submit", async (ev)=>{
    ev.preventDefault();
    ok.hidden=true; err.hidden=true;
    try{
      const fd = new FormData(form);
      const sid = selectedStationId();
      if (sid) fd.set("station_id", sid);
      await api("/api/profile",{method:"POST",body:fd,headers:{}});
      ok.textContent="Guardado.";
      ok.hidden=false;
      form.fiel_cer.value=""; form.fiel_key.value="";
      await load();
    }catch(e){
      err.textContent="Error: "+e.message;
      err.hidden=false;
    }
  });

  await load();
})();
