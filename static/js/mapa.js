(async ()=>{
  let me; try{ me=(await api("/api/me")).me; }catch(e){ location.href="/login"; return; }
  let stations = [];
  try{ stations = (await api("/api/map/stations")).stations || []; }
  catch(e){ stations = (await api("/api/stations")).stations || []; }

  const mx = [23.6345, -102.5528];
  const map = L.map('map', { zoomControl: true }).setView(mx, 5);

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap'
  }).addTo(map);

  const bounds = [];
  const stationLayer = L.layerGroup().addTo(map);

  stations.forEach(s=>{
    const lat = (s.lat===0||s.lat)? Number(s.lat) : null;
    const lng = (s.lng===0||s.lng)? Number(s.lng) : null;
    if (lat !== null && !Number.isNaN(lat) && lng !== null && !Number.isNaN(lng)){
      const pos = [lat, lng];
      bounds.push(pos);
      const status = s.monthly_status || "active";
      const badge = status==="active" ? "✅ Activa" : "⚠️ Vista";
      const popup = `
        <div style="font-weight:900;">${s.name}</div>
        <div class="muted">${s.code} • ${s.city||""} ${s.state||""}</div>
        <div class="muted">Mensualidad: <b>${badge}</b></div>
      `;
      const brand = (s.brand||"consulting");
      const clr = brand==="petroleum" ? "#2F6FED" : "#18A070";
      const edge = brand==="petroleum" ? "#60A5FA" : "#34D399";
      L.circleMarker(pos, {radius:8, color:edge, weight:2, fillColor:clr, fillOpacity:0.9})
        .addTo(stationLayer)
        .bindPopup(popup);

    }
  });

  if (bounds.length){
    map.fitBounds(bounds, { padding:[30,30] });
  }

  // ---- OSM fuel stations (dynamic) ----
  const toggleFuel = document.getElementById("toggleFuel");
  const btnFuelRefresh = document.getElementById("btnFuelRefresh");
  const fuelCount = document.getElementById("fuelCount");
  const fuelLayer = (L.markerClusterGroup ? L.markerClusterGroup({
    chunkedLoading: true,
    showCoverageOnHover: false,
    spiderfyOnMaxZoom: true,
    disableClusteringAtZoom: 15,
  }) : L.layerGroup());
  let fullFuelList = [];
  let currentBrand = "ALL";
  const fuelBrand = document.getElementById("fuelBrand");
  const fuelBrandWrap = document.getElementById("fuelBrandWrap");

  function setFuelUi(visible){
    if (!btnFuelRefresh) return;
    btnFuelRefresh.style.display = visible ? "" : "none";
    if (fuelBrandWrap) fuelBrandWrap.style.display = visible ? "inline-flex" : "none";
    if (!visible){ fuelCount && (fuelCount.textContent=""); }
    if (!visible && fuelBrand){ fuelBrand.innerHTML=""; currentBrand="ALL"; }
  }

    function normBrand(p){
    return (p.brand || p.operator || "").trim() || "Sin marca";
  }

  function populateBrandFilter(list){
    if (!fuelBrand) return;
    const brands = Array.from(new Set(list.map(normBrand))).sort((a,b)=>a.localeCompare(b));
    fuelBrand.innerHTML = "";
    const optAll = document.createElement("option");
    optAll.value = "ALL"; optAll.textContent = "Todas";
    fuelBrand.appendChild(optAll);
    brands.forEach(b=>{
      const o=document.createElement("option");
      o.value=b; o.textContent=b;
      fuelBrand.appendChild(o);
    });
    fuelBrand.value = currentBrand || "ALL";
  }

  function renderFuelMarkers(){
    if (!toggleFuel || !toggleFuel.checked) return;
    fuelLayer.clearLayers();
    const list = (currentBrand && currentBrand!=="ALL")
      ? fullFuelList.filter(p=>normBrand(p)===currentBrand)
      : fullFuelList;

    list.slice(0, 1200).forEach(p=>{
      const popup = `
        <div style="font-weight:900;">${p.name||"Gasolinera"}</div>
        <div class="muted">${normBrand(p)}</div>
        <div class="muted">Fuente: OpenStreetMap</div>
      `;
      // Use markers (cluster-friendly)
      const m = L.marker([p.lat, p.lng], { riseOnHover:true }).bindPopup(popup);
      fuelLayer.addLayer(m);
    });

    fuelCount && (fuelCount.textContent = `${list.length} gasolineras visibles (OSM)${currentBrand!=="ALL" ? " • Filtro: "+currentBrand : ""}.`);
  }

async function loadFuel(){
    if (!toggleFuel || !toggleFuel.checked) return;
    // Avoid loading at very low zoom (too many results)
    if (map.getZoom() < 9){
      fuelCount && (fuelCount.textContent = "Acércate (zoom 9+) para cargar gasolineras en la zona visible.");
      return;
    }
    const b = map.getBounds();
    const bbox = [b.getSouth(), b.getWest(), b.getNorth(), b.getEast()].join(",");
    fuelCount && (fuelCount.textContent = "Cargando gasolineras (OSM)...");
    let resp;
    try{
      resp = await api("/api/map/fuel?bbox="+encodeURIComponent(bbox));
    }catch(e){
      fuelCount && (fuelCount.textContent = "No se pudo cargar (OSM). Intenta de nuevo.");
      return;
    }
    const list = (resp.fuel || []).slice(0, 800); // hard cap for UI safety
    fuelLayer.clearLayers();
    list.forEach(p=>{
      const popup = `
        <div style="font-weight:900;">${p.name||"Gasolinera"}</div>
        <div class="muted">${p.brand||""} ${p.operator||""}</div>
        <div class="muted">Fuente: OpenStreetMap</div>
      `;
      L.circleMarker([p.lat, p.lng], { radius: 6 }).addTo(fuelLayer).bindPopup(popup);
    });
    fuelCount && (fuelCount.textContent = `${list.length} gasolineras visibles (OSM).`);
  }

  if (toggleFuel){
    toggleFuel.addEventListener("change", async ()=>{
      if (toggleFuel.checked){
        fuelLayer.addTo(map);
        setFuelUi(true);
        await loadFuel();
      }else{
        map.removeLayer(fuelLayer);
        fuelLayer.clearLayers();
        setFuelUi(false);
      }
    });
  }
  if (btnFuelRefresh){
    btnFuelRefresh.addEventListener("click", loadFuel);
  }
  if (fuelBrand){
    fuelBrand.addEventListener("change", ()=>{
      currentBrand = fuelBrand.value || "ALL";
      renderFuelMarkers();
    });
  }

  // Debounce loading after move/zoom
  let t=null;
  map.on("moveend zoomend", ()=>{
    if (!toggleFuel || !toggleFuel.checked) return;
    clearTimeout(t);
    t=setTimeout(loadFuel, 600);
  });

})();
