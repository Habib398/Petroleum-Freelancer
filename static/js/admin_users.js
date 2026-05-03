(async ()=>{
  const err = qs("#uErr");
  const stationSel = qs("#uStation");

  let stations = [];

  function escapeHtml(str){
    return String(str)
      .replaceAll('&','&amp;')
      .replaceAll('<','&lt;')
      .replaceAll('>','&gt;')
      .replaceAll('"','&quot;')
      .replaceAll("'",'&#39;');
  }

  async function loadStations(){
    stations = (await api("/api/stations")).stations || [];
    stationSel.innerHTML = `<option value="">(Sin estación)</option>` +
      stations.map(s=>`<option value="${s.id}">${s.code} • ${s.name}</option>`).join("");
  }

  function stationNameById(id){
    const s = stations.find(x=>String(x.id)===String(id));
    return s ? `${s.code} • ${s.name}` : "—";
  }

  function roleLabel(role){
    const map = {
      admin: "Administrador",
      operador: "Operador",
      jefe_estacion: "Jefe de estación",
      contador: "Contador",
      auditor: "Auditor"
    };
    return map[role] || role;
  }

  async function refresh(){
    const users = (await api("/api/users")).users || [];
    const tb = qs("#uT");
    tb.innerHTML = users.map(u=>`
      <tr data-id="${u.id}">
        <td>${u.id}</td>
        <td><b>${escapeHtml(u.username)}</b></td>
        <td>${u.email ? escapeHtml(u.email) : "—"}</td>
        <td>${roleLabel(u.role)}</td>
        <td>${u.station_name||"—"}</td>
        <td>${u.is_active? "Sí":"No"}</td>
        <td style="white-space:nowrap;">
          <button class="btn sm" data-act="access">Accesos</button>
          <button class="btn sm" data-act="edit">Editar</button>
          <button class="btn sm danger" data-act="del">Eliminar</button>
        </td>
      </tr>
    `).join("");
  }

  async function doCreate(){
    err.hidden=true;
    try{
      const role = qs("#uRole").value;
      const station_id = stationSel.value || null;
      await api("/api/users",{method:"POST",body:JSON.stringify({
        username:qs("#uName").value,
        password:qs("#uPass").value,
        email:(qs("#uEmail")?.value || "").trim(),
        role,
        station_id: role==="admin"? null : station_id,
        allowed_brands: (qs("#uBrands")?qs("#uBrands").value:"")
      })});
      toast("Creado","Usuario creado.");
      qs("#uName").value=""; qs("#uPass").value=""; if(qs("#uEmail")) qs("#uEmail").value="";
      await refresh();
    }catch(e){
      err.textContent="Error: "+e.message;
      err.hidden=false;
    }
  }

  qs("#uAdd").addEventListener("click", doCreate);

  // Event delegation for edit/delete
  qs("#uT").addEventListener("click", async (ev)=>{
    const btn = ev.target.closest("button[data-act]");
    if(!btn) return;
    const tr = ev.target.closest("tr[data-id]");
    if(!tr) return;
    const user_id = tr.getAttribute("data-id");
    const act = btn.getAttribute("data-act");

    if(act === "access"){
      const dlg = qs("#dlgAccess");
      const meta = qs("#accessMeta");
      const list = qs("#accessList");
      const errBox = qs("#accessErr");
      const btnAll = qs("#accessAll");
      const btnNone = qs("#accessNone");
      const btnSave = qs("#accessSave");

      errBox && (errBox.hidden=true);
      // latest user record
      const users = (await api("/api/users")).users || [];
      const u = users.find(x=>String(x.id)===String(user_id));
      if(!u){ toast("Error","Usuario no encontrado", {type:"error"}); return; }

      // stations for current brand
      await loadStations();
      const access = await api(`/api/users/${user_id}/station-access`);
      const selected = new Set((access.stations || []).map(String));

      if(meta) meta.textContent = `${u.username} • ${roleLabel(u.role)} • ${u.station_name||"(Sin estación)"}`;
      if(list){
        list.innerHTML = stations.length ? stations.map(s=>{
          const id = String(s.id);
          const checked = selected.has(id) ? "checked" : "";
          return `
            <label class="card" style="padding:10px;display:flex;gap:10px;align-items:center;">
              <input type="checkbox" class="acc-chk" value="${id}" ${checked}>
              <div>
                <div style="font-weight:900;">${escapeHtml(s.code)} • ${escapeHtml(s.name)}</div>
                <div class="help">${escapeHtml(s.city||"")} ${escapeHtml(s.state||"")}</div>
              </div>
            </label>
          `;
        }).join("") : `<div class="help">No hay estaciones en este sistema. Crea estaciones primero.</div>`;
      }

      if(btnAll) btnAll.onclick = ()=> qsa(".acc-chk", list).forEach(c=> c.checked = true);
      if(btnNone) btnNone.onclick = ()=> qsa(".acc-chk", list).forEach(c=> c.checked = false);

      if(btnSave){
        btnSave.onclick = async (e)=>{
          e.preventDefault();
          errBox && (errBox.hidden=true);
          try{
            const ids = qsa(".acc-chk", list).filter(c=>c.checked).map(c=>Number(c.value));
            await api(`/api/users/${user_id}/station-access`, { method:"PUT", body: JSON.stringify({ stations: ids }) });
            toast("Guardado","Accesos actualizados.");
            dlg && dlg.close();
          }catch(e2){
            const msg = e2.message || "No se pudo guardar";
            if(errBox){ errBox.textContent = "Error: " + msg; errBox.hidden=false; }
            else toast("Error", msg, {type:"error"});
          }
        };
      }

      dlg && dlg.showModal();
      return;
    }

    if(act === "del"){
      if(!confirm("¿Eliminar este usuario? Esta acción no se puede deshacer.")) return;
      try{
        await api(`/api/users/${user_id}`, { method:"DELETE" });
        toast("Eliminado","Usuario eliminado.");
        await refresh();
      }catch(e){
        toast("No se pudo eliminar", e.message || "Error", {type:"error"});
      }
      return;
    }

    if(act === "edit"){
      // Get latest user record
      const users = (await api("/api/users")).users || [];
      const u = users.find(x=>String(x.id)===String(user_id));
      if(!u){ toast("Error","Usuario no encontrado", {type:"error"}); return; }

      // Simple prompt-based editor (rápido y sin dependencias)
      const newUsername = prompt("Usuario:", u.username);
      if(newUsername === null) return;

      const newRole = prompt("Rol (admin|operador|jefe_estacion|contador|auditor):", u.role);
      if(newRole === null) return;

      const newEmail = prompt("Correo (vacío para quitar):", u.email || "");
      if(newEmail === null) return;

      let newStationId = u.station_id;
      if(newRole !== "admin"){
        const currentStation = u.station_id ? stationNameById(u.station_id) : "(Sin estación)";
        const rawStation = prompt(
          "ID de estación (número) o vacío para quitar.\nActual: " + currentStation + "\nTip: revisa la lista en Estaciones.",
          u.station_id || ""
        );
        if(rawStation === null) return;
        newStationId = rawStation.trim() === "" ? null : Number(rawStation);
      }else{
        newStationId = null;
      }

      const rawActive = prompt("¿Activo? (1=Sí, 0=No):", u.is_active ? "1" : "0");
      if(rawActive === null) return;
      const is_active = rawActive.trim() === "0" ? 0 : 1;

      const newPassword = prompt("Nueva contraseña (deja vacío para no cambiar):", "");
      if(newPassword === null) return;

      const payload = {
        username: String(newUsername).trim(),
        email: String(newEmail || "").trim(),
        role: String(newRole).trim(),
        station_id: newStationId,
        is_active
      };
      if(newPassword.trim()) payload.password = newPassword.trim();

      try{
        await api(`/api/users/${user_id}`, { method:"PUT", body: JSON.stringify(payload) });
        toast("Actualizado","Cambios guardados.");
        await refresh();
      }catch(e){
        toast("No se pudo actualizar", e.message || "Error", {type:"error"});
      }
    }
  });

  await loadStations();
  await refresh();
})();
