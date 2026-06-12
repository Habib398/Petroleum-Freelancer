(async ()=>{
  const err = qs("#uErr");
  const userModal = qs("#userModal");
  const modalClose = qs("#modalClose");
  const btnNewUser = qs("#btnNewUser");
  const searchInput = qs("#searchUsers");
  const filterRole = qs("#filterRole");
  const filterActive = qs("#filterActive");
  const btnToggleFilters = qs("#btnToggleFilters");
  const filtersPanel = qs("#filtersPanel");
  const btnClearFilters = qs("#btnClearFilters");
  const filterInfo = qs("#filterInfo");
  const usersContainer = qs("#usersContainer");
  const stationSel = qs("#uStation");

  let stations = [];
  let allUsers = [];

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

  function openModal(isNew = true){
    qs("#modalTitle").textContent = isNew ? "Nuevo usuario" : "Editar usuario";
    qs("#uAdd").textContent = isNew ? "Crear usuario" : "Guardar cambios";
    userModal.classList.add("active");
  }

  function closeModal(){
    userModal.classList.remove("active");
    resetForm();
  }

  function resetForm(){
    qs("#uId").value = "";
    qs("#uName").value = "";
    qs("#uPass").value = "";
    qs("#uEmail").value = "";
    qs("#uRole").value = "operador";
    qs("#uStation").value = "";
    qs("#uBrands").value = "consulting,petroleum";
    err.hidden = true;
  }

  function getFilteredUsers(){
    const searchTerm = searchInput.value.toLowerCase().trim();
    const roleFilter = filterRole.value;
    const activeFilter = filterActive.value;

    return allUsers.filter(u => {
      const matchSearch = !searchTerm || 
        u.username.toLowerCase().includes(searchTerm) ||
        (u.email || '').toLowerCase().includes(searchTerm) ||
        (u.station_name || '').toLowerCase().includes(searchTerm);
      
      const matchRole = !roleFilter || u.role === roleFilter;
      const matchActive = !activeFilter || (activeFilter === "true" ? u.is_active : !u.is_active);
      
      return matchSearch && matchRole && matchActive;
    });
  }

  function updateFilterInfo(){
    const filtered = getFilteredUsers();
    const isFiltered = searchInput.value || filterRole.value || filterActive.value;
    
    if(isFiltered){
      filterInfo.textContent = `Mostrando ${filtered.length} de ${allUsers.length} usuarios`;
      filterInfo.style.display = 'block';
    } else {
      filterInfo.style.display = 'none';
    }
  }

  function applyFilters(){
    renderTable(getFilteredUsers());
    updateFilterInfo();
  }

  function renderTable(users){
    if(users.length === 0){
      usersContainer.innerHTML = `
        <div class="empty-message">
          <div style="font-weight: 600; margin-bottom: 8px;">No hay usuarios que coincidan</div>
          <div>Intenta ajustar los filtros de búsqueda</div>
        </div>
      `;
      return;
    }

    usersContainer.innerHTML = `
      <div class="tablewrap">
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Usuario</th>
              <th>Correo</th>
              <th>Rol</th>
              <th>Estación</th>
              <th>Estado</th>
              <th>Acciones</th>
            </tr>
          </thead>
          <tbody id="uT"></tbody>
        </table>
      </div>
    `;

    const tbody = qs("#uT");
    tbody.innerHTML = users.map(u=>`
      <tr data-id="${u.id}">
        <td>${u.id}</td>
        <td><b>${escapeHtml(u.username)}</b></td>
        <td>${u.email ? escapeHtml(u.email) : "—"}</td>
        <td>${roleLabel(u.role)}</td>
        <td>${u.station_name||"—"}</td>
        <td>${u.is_active? "Activo":"Inactivo"}</td>
        <td style="white-space:nowrap;">
          <button class="btn ghost small" data-act="access">Accesos</button>
          <button class="btn ghost small" data-act="edit">Editar</button>
          <button class="btn danger small" data-act="del">Eliminar</button>
        </td>
      </tr>
    `).join("");

    // Event delegation
    tbody.addEventListener("click", handleTableClick);
  }

  async function handleTableClick(ev){
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
      const u = allUsers.find(x=>String(x.id)===String(user_id));
      if(!u){ toast("Error","Usuario no encontrado", {type:"error"}); return; }

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
        }).join("") : `<div class="help">No hay estaciones. Crea estaciones primero.</div>`;
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
      const u = allUsers.find(x=>String(x.id)===String(user_id));
      if(!u){ toast("Error","Usuario no encontrado", {type:"error"}); return; }

      qs("#uId").value = u.id;
      qs("#uName").value = u.username;
      qs("#uPass").value = "";
      qs("#uEmail").value = u.email || "";
      qs("#uRole").value = u.role;
      qs("#uStation").value = u.station_id || "";
      qs("#uBrands").value = u.allowed_brands || "consulting,petroleum";
      
      openModal(false);
      return;
    }
  }

  async function doCreate(){
    err.hidden = true;
    try{
      const userId = qs("#uId").value;
      const role = qs("#uRole").value;
      const station_id = qs("#uStation").value || null;
      const payload = {
        username: qs("#uName").value,
        email: (qs("#uEmail")?.value || "").trim(),
        role,
        station_id: role==="admin"? null : station_id,
        allowed_brands: (qs("#uBrands")?.value || "")
      };

      if(userId){
        // Edit mode
        if(qs("#uPass").value){
          payload.password = qs("#uPass").value;
        }
        await api(`/api/users/${userId}`, {method:"PUT", body:JSON.stringify(payload)});
        toast("Actualizado","Usuario actualizado correctamente.");
      } else {
        // Create mode
        payload.password = qs("#uPass").value;
        await api("/api/users",{method:"POST",body:JSON.stringify(payload)});
        toast("Creado","Usuario creado correctamente.");
      }

      closeModal();
      await refresh();
    }catch(e){
      err.textContent="Error: "+e.message;
      err.hidden=false;
    }
  }

  async function refresh(){
    allUsers = (await api("/api/users")).users || [];
    applyFilters();
  }

  // Event listeners
  btnNewUser.addEventListener("click", ()=> openModal(true));
  modalClose.addEventListener("click", ()=> closeModal());
  userModal.addEventListener("click", (e)=>{ if(e.target === userModal) closeModal(); });

  btnToggleFilters.addEventListener("click", ()=>{
    if(filtersPanel.classList.contains("active")){
      filtersPanel.classList.remove("active");
      btnToggleFilters.style.backgroundColor = '';
    } else {
      filtersPanel.classList.add("active");
      btnToggleFilters.style.backgroundColor = 'var(--hme-bg)';
    }
  });

  searchInput.addEventListener("input", applyFilters);
  filterRole.addEventListener("change", applyFilters);
  filterActive.addEventListener("change", applyFilters);
  btnClearFilters.addEventListener("click", ()=>{
    searchInput.value = "";
    filterRole.value = "";
    filterActive.value = "";
    applyFilters();
  });

  qs("#uAdd").addEventListener("click", doCreate);

  await loadStations();
  await refresh();
})();
