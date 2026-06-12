(async ()=>{
  const err = qs("#sErr");
  const stationModal = qs("#stationModal");
  const modalClose = qs("#modalClose");
  const btnNewStation = qs("#btnNewStation");
  const kmlModal = qs("#kmlModal");
  const kmlModalClose = qs("#kmlModalClose");
  const searchInput = qs("#searchStations");
  const filterBrand = qs("#filterBrand");
  const filterStatus = qs("#filterStatus");
  const btnClearFilters = qs("#btnClearFilters");
  const btnToggleFilters = qs("#btnToggleFilters");
  const filtersPanel = qs("#filtersPanel");
  const filterInfo = qs("#filterInfo");

  function getCsrfToken(){
    const meta = document.querySelector('meta[name="csrf-token"]');
    if(meta && meta.content) return meta.content;
    const m = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
    if(m) return decodeURIComponent(m[1]);
    if(window.__csrf) return window.__csrf;
    return "";
  }

  function dmsToDecimal(deg, min, sec, dir){
    let dec = Number(deg) + Number(min)/60 + Number(sec)/3600;
    if (dir === 'S' || dir === 'W') dec *= -1;
    return dec;
  }

  function parseCoord(raw){
    const s = (raw||"").trim();
    if(!s) return null;
    const decMatch = s.match(/(-?\d+(?:\.\d+)?)\s*[,\s]\s*(-?\d+(?:\.\d+)?)/);
    if (decMatch){
      const lat = Number(decMatch[1]);
      const lng = Number(decMatch[2]);
      if(!Number.isNaN(lat) && !Number.isNaN(lng)) return {lat, lng};
    }
    const r = /(\d+)°(\d+)'([\d.]+)\"?([NSEW])/gi;
    let m, vals=[];
    while((m=r.exec(s))!==null){
      vals.push(dmsToDecimal(m[1], m[2], m[3], m[4].toUpperCase()));
    }
    if (vals.length >= 2){
      return {lat: vals[0], lng: vals[1]};
    }
    return null;
  }

  // Modal control
  function openModal(isNew = true){
    qs("#modalTitle").textContent = isNew ? "Nueva estación" : "Editar estación";
    qs("#sAdd").textContent = isNew ? "Crear estación" : "Guardar cambios";
    stationModal.classList.add("active");
  }

  function closeModal(){
    stationModal.classList.remove("active");
    resetForm();
  }

  function resetForm(){
    qs("#sId").value="";
    ["#sName","#sCode","#sNum","#sGroup","#sState","#sCity","#sAddr","#sCoord","#sLat","#sLng"].forEach(sel=>{ const el=qs(sel); if(el) el.value=""; });
    qs("#sBrand").value = "consulting";
    qs("#sMonthlyEnd").value = "";
    err.hidden = true;
    qs("#sCancelEdit").hidden = true;
  }

  // Filter logic
  function getFilteredStations(){
    const searchTerm = searchInput.value.toLowerCase().trim();
    const brandFilter = filterBrand.value;
    const statusFilter = filterStatus.value;
    
    return lastStations.filter(s => {
      const matchSearch = !searchTerm || 
        s.name.toLowerCase().includes(searchTerm) ||
        s.code.toLowerCase().includes(searchTerm) ||
        (s.city || '').toLowerCase().includes(searchTerm) ||
        (s.state || '').toLowerCase().includes(searchTerm);
      
      const matchBrand = !brandFilter || (s.brand || 'consulting') === brandFilter;
      const matchStatus = !statusFilter || s.monthly_status === statusFilter;
      
      return matchSearch && matchBrand && matchStatus;
    });
  }

  function updateFilterInfo(){
    const filtered = getFilteredStations();
    const isFiltered = searchInput.value || filterBrand.value || filterStatus.value;
    
    if(isFiltered){
      filterInfo.textContent = `Mostrando ${filtered.length} de ${lastStations.length} estaciones`;
      filterInfo.style.display = 'block';
    } else {
      filterInfo.style.display = 'none';
    }
  }

  function applyFilters(){
    const filtered = getFilteredStations();
    renderStations(filtered);
    updateFilterInfo();
  }

  // Modal eventos
  btnNewStation.addEventListener("click", ()=> openModal(true));
  modalClose.addEventListener("click", ()=> closeModal());
  kmlModalClose.addEventListener("click", ()=> kmlModal.classList.remove("active"));
  stationModal.addEventListener("click", (e)=>{ if(e.target === stationModal) closeModal(); });
  kmlModal.addEventListener("click", (e)=>{ if(e.target === kmlModal) kmlModal.classList.remove("active"); });
  
  // Filter eventos
  btnToggleFilters.addEventListener("click", ()=>{
    if(filtersPanel.style.display === 'none'){
      filtersPanel.style.display = 'flex';
      btnToggleFilters.style.backgroundColor = 'var(--hme-bg)';
    } else {
      filtersPanel.style.display = 'none';
      btnToggleFilters.style.backgroundColor = '';
    }
  });
  
  searchInput.addEventListener("input", applyFilters);
  filterBrand.addEventListener("change", applyFilters);
  filterStatus.addEventListener("change", applyFilters);
  btnClearFilters.addEventListener("click", ()=>{
    searchInput.value = "";
    filterBrand.value = "";
    filterStatus.value = "";
    applyFilters();
  });

  let lastStations = [];
  
  function renderStations(stations){
    const container = qs("#stationsList");
    
    if(stations.length === 0){
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon" style="font-size: 32px; color: var(--hme-text-soft);">◆</div>
          <div style="font-weight: 600; margin-bottom: 8px;">No hay estaciones que coincidan</div>
          <div>Intenta ajustar los filtros de búsqueda</div>
        </div>
      `;
      return;
    }

    container.innerHTML = stations.map(s=>`
      <div class="station-row" data-station-id="${s.id}">
        <div style="display: flex; align-items: center; justify-content: center; width: 48px; height: 48px; background: ${(s.brand||"consulting")==="petroleum" ? "var(--hme-petroleum-light, rgba(226, 113, 113, 0.1))" : "var(--hme-consulting-light, rgba(76, 159, 211, 0.1))"}; border-radius: 8px; font-size: 20px; flex-shrink: 0; font-weight: 600; color: var(--hme-text-soft);">
          ◆
        </div>
        <div class="station-info">
          <div class="station-name">${s.name}</div>
          <div class="station-meta">
            <span class="station-meta-item"><strong>${s.code}</strong></span>
            <span class="station-meta-item">${s.city||""} ${s.state||""}</span>
            <span class="pill ${(s.brand||"consulting")==="petroleum" ? "pill-petroleum" : "pill-consulting"}">${(s.brand||"consulting")==="petroleum" ? "Petroleum" : "Consulting"}</span>
            <span class="pill" style="background: ${s.monthly_status === 'active' ? 'var(--hme-success, #10b981)' : s.monthly_status === 'expired' ? 'var(--hme-danger, #ef4444)' : 'var(--hme-warning, #f59e0b)'}; color: white; font-size: 12px;">${s.monthly_status === 'active' ? 'Activa' : s.monthly_status === 'expired' ? 'Expirada' : 'Solo vista'}</span>
          </div>
        </div>
        <div class="station-actions">
          <button class="btn ghost small" data-edit="${s.id}">Editar</button>
          <button class="btn danger small" data-del="${s.id}">Eliminar</button>
          <div style="width: 100%; height: 0;"></div>
          <button class="btn ghost small" data-set="${s.id}" data-status="active">Activar</button>
          <button class="btn ghost small" data-set="${s.id}" data-status="view_only">Solo vista</button>
          <button class="btn ghost small" data-set="${s.id}" data-status="expired">Expirada</button>
        </div>
      </div>
    `).join("");

    // Event listeners
    qsa("[data-set]").forEach(b=>b.addEventListener("click", async ()=>{
      await api(`/api/stations/${b.dataset.set}`,{method:"PUT",body:JSON.stringify({monthly_status:b.dataset.status})});
      toast("Actualizado","Status actualizado.");
      await refresh();
    }));

    qsa("[data-edit]").forEach(b=>b.addEventListener("click", ()=>{
      const s = lastStations.find(x=>String(x.id)===String(b.dataset.edit));
      if(!s) return;
      qs("#sId").value = s.id;
      qs("#sName").value = s.name||"";
      qs("#sCode").value = s.code||"";
      qs("#sBrand").value = (s.brand||"consulting");
      qs("#sMonthlyEnd").value = (s.monthly_end||"");
      qs("#sNum").value = (s.station_number!=null? s.station_number: "");
      qs("#sGroup").value = s.group_name||"";
      qs("#sState").value = s.state||"";
      qs("#sCity").value = s.city||"";
      qs("#sAddr").value = s.address||"";
      qs("#sCoord").value = (s.lat!=null && s.lng!=null) ? `${s.lat}, ${s.lng}` : "";
      if (qs("#sCoord").value) syncLatLng();
      openModal(false);
    }));

    qsa("[data-del]").forEach(b=>b.addEventListener("click", async ()=>{
      const id = b.dataset.del;
      if(!confirm("¿Eliminar esta estación? Se eliminarán también sus eventos y entregas relacionadas.")) return;
      await api(`/api/stations/${id}`, {method:"DELETE"});
      toast("Eliminada","Estación eliminada correctamente.");
      await refresh();
    }));
  }
  
  async function refresh(){
    const st = (await api("/api/stations")).stations || [];
    lastStations = st;
    applyFilters();
  }

  const sCoord = qs("#sCoord");
  function syncLatLng(){
    const res = parseCoord(sCoord?.value);
    if(res){
      qs("#sLat").value = res.lat.toFixed(6);
      qs("#sLng").value = res.lng.toFixed(6);
      return res;
    } else {
      qs("#sLat").value = "";
      qs("#sLng").value = "";
      return null;
    }
  }
  if (sCoord){
    sCoord.addEventListener("input", ()=>{ syncLatLng(); });
    sCoord.addEventListener("blur", ()=>{ syncLatLng(); });
  }

  // Map preview dialog
  const dlg = qs("#dlgStationMap");
  const btnPrev = qs("#sPreview");
  const btnClose = qs("#sMapClose");
  let map=null, marker=null;
  if(btnPrev && dlg){
    btnPrev.addEventListener("click", ()=>{
      const res = syncLatLng();
      if(!res){
        toast("Coordenada inválida","Ingresa una coordenada válida (DMS o decimal).");
        return;
      }
      dlg.showModal();
      setTimeout(()=>{
        if(!map){
          map = L.map('stationMap').setView([res.lat, res.lng], 12);
          L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '&copy; OpenStreetMap' }).addTo(map);
        }
        map.setView([res.lat, res.lng], 12);
        if(marker){ marker.remove(); }
        marker = L.marker([res.lat, res.lng]).addTo(map);
      }, 50);
    });
  }
  if(btnClose && dlg) btnClose.addEventListener("click", ()=> dlg.close());

  qs("#sAdd").addEventListener("click", async ()=>{
    const editingId = (qs("#sId").value||"").trim();
    err.hidden=true;
    try{
      await api(editingId?`/api/stations/${editingId}`:"/api/stations",{method: editingId?"PUT":"POST",body:JSON.stringify({
        brand:(qs("#sBrand")?qs("#sBrand").value:"consulting"),
        name:qs("#sName").value, code:qs("#sCode").value,
        station_number: qs("#sNum").value? Number(qs("#sNum").value): null,
        group_name: qs("#sGroup").value,
        monthly_end: (qs("#sMonthlyEnd")?qs("#sMonthlyEnd").value:null),
        state:qs("#sState").value, city:qs("#sCity").value,
        address:qs("#sAddr").value,
        lat:qs("#sLat").value? Number(qs("#sLat").value): null,
        lng:qs("#sLng").value? Number(qs("#sLng").value): null
      })});
      toast(editingId?"Actualizada":"Creada", editingId?"Estación actualizada correctamente.":"Estación creada correctamente.");
      closeModal();
      await refresh();
    }catch(e){
      err.textContent="Error: "+e.message;
      err.hidden=false;
    }
  });

  // --- KML Import ---
  const kmlBtn = qs("#kmlImport");
  const kmlFile = qs("#kmlFile");
  const kmlMsg = qs("#kmlMsg");
  
  // Botón para abrir modal KML (si existe)
  const btnImportKml = qsa("button").find(b=>b.textContent.includes("KML") || b.textContent.includes("Importar"));
  if(btnImportKml) btnImportKml.addEventListener("click", ()=> kmlModal.classList.add("active"));

  if(kmlBtn && kmlFile){
    kmlBtn.addEventListener("click", async ()=>{
      kmlMsg && (kmlMsg.hidden=true);
      const f = (kmlFile.files||[])[0];
      if(!f){ toast("Falta archivo","Selecciona un archivo .kml"); return; }
      const fd = new FormData();
      fd.append("file", f);
      kmlBtn.disabled = true;
      try{
        const r = await fetch("/api/stations/import-kml", {method:"POST", body: fd, credentials:"include", headers: {"X-CSRF-Token": getCsrfToken()}});
        const data = await r.json().catch(()=>({ok:false,error:"Respuesta inválida"}));
        if(!r.ok || !data.ok){
          const msg = data.error || ("Error HTTP " + r.status);
          if(kmlMsg){ kmlMsg.textContent = msg; kmlMsg.hidden=false; }
          toast("Error", msg);
          return;
        }
        const msg = `Importadas: ${data.count} estaciones · Omitidas: ${data.skipped}`;
        if(kmlMsg){ kmlMsg.textContent = msg; kmlMsg.hidden=false; }
        toast("Importación completada", msg);
        kmlFile.value = "";
        await refresh();
      }catch(e){
        const msg = e.message || "Error al importar archivo";
        if(kmlMsg){ kmlMsg.textContent = msg; kmlMsg.hidden=false; }
        toast("Error", msg);
      }finally{
        kmlBtn.disabled = false;
      }
    });
  }

  await refresh();
})();
